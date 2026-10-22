"""Fatia 2 — agendamento: janela de doca, capacidade finita, prioridade e rastro.

Revision ID: 0002_fatia2_scheduling
Create Date: 2026-09-20

Invariantes que ficam no banco:
  - doca não tem dois agendamentos ativos sobrepostos     (EXCLUDE parcial)
  - veículo não tem dois agendamentos ativos sobrepostos  (EXCLUDE parcial)
  - capacidade de recurso nunca fica negativa             (CHECK)
  - reserva de vaga é exclusiva no tempo                  (EXCLUDE parcial)
  - reprogramação sem motivo não existe                   (CHECK)
  - versão do agregado só cresce                          (trigger de concorrência otimista)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0002_fatia2_scheduling"
down_revision = "0001_fatia1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE resource (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(32) NOT NULL UNIQUE,
            kind varchar(32) NOT NULL,
            capacity integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_resource_kind CHECK (kind IN
                ('forklift','hopper','labor_crew','crane','pump','inspector')),
            CONSTRAINT ck_resource_capacity CHECK (capacity > 0)
        );

        CREATE TABLE shift_calendar (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(32) NOT NULL UNIQUE,
            weekday smallint NOT NULL,
            starts_time time NOT NULL,
            ends_time time NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_shift_weekday CHECK (weekday BETWEEN 0 AND 6),
            CONSTRAINT ck_shift_window CHECK (ends_time > starts_time)
        );

        CREATE TABLE plant_stoppage (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            reason_code varchar(48) NOT NULL,
            period tstzrange NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ex_plant_stoppage EXCLUDE USING gist (plant_id WITH =, period WITH &&)
        );

        CREATE TABLE priority_rule (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(48) NOT NULL UNIQUE,
            rank integer NOT NULL,
            match_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_priority_rank CHECK (rank > 0)
        );
        CREATE UNIQUE INDEX uq_priority_rule_rank ON priority_rule(rank) WHERE active;
        """
    )

    _exec(
        """
        CREATE TABLE appointment (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            reference varchar(24) NOT NULL UNIQUE,
            state varchar(16) NOT NULL DEFAULT 'requested',
            dock_id uuid NOT NULL REFERENCES dock(id),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            driver_id uuid REFERENCES driver(id),
            carrier_id uuid REFERENCES carrier(id),
            product_id uuid REFERENCES product(id),
            operation_type_id uuid NOT NULL REFERENCES operation_type(id),
            resource_id uuid REFERENCES resource(id),
            visit_id uuid REFERENCES visit(id),
            starts_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            priority_code varchar(48),
            priority_rank integer NOT NULL DEFAULT 999,
            slot_id uuid REFERENCES slot(id),
            created_by varchar(120),
            channel varchar(16) NOT NULL DEFAULT 'internal',
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_appointment_state CHECK (state IN
                ('draft','requested','confirmed','checked_in','in_progress',
                 'completed','cancelled','no_show','rescheduled')),
            CONSTRAINT ck_appointment_window CHECK (ends_at > starts_at),
            CONSTRAINT ck_appointment_version CHECK (version >= 1),
            CONSTRAINT ck_appointment_channel CHECK (channel IN ('internal','portal','api')),
            CONSTRAINT ex_appointment_dock EXCLUDE USING gist (
                dock_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
                WHERE (state IN ('confirmed','checked_in','in_progress')),
            CONSTRAINT ex_appointment_vehicle EXCLUDE USING gist (
                vehicle_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
                WHERE (state IN ('confirmed','checked_in','in_progress'))
        );
        CREATE SEQUENCE appointment_reference_seq;
        CREATE INDEX ix_appointment_window ON appointment(starts_at, ends_at);
        CREATE INDEX ix_appointment_state ON appointment(state);

        CREATE TABLE appointment_change_log (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            appointment_id uuid NOT NULL REFERENCES appointment(id),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            actor varchar(120),
            reason_code varchar(48),
            from_state varchar(16),
            to_state varchar(16),
            from_starts_at timestamptz,
            to_starts_at timestamptz,
            impact_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_change_log_reason CHECK (
                to_state NOT IN ('rescheduled','cancelled') OR reason_code IS NOT NULL)
        );
        CREATE INDEX ix_appointment_change_log_appointment_id
            ON appointment_change_log(appointment_id, occurred_at DESC);

        CREATE TABLE slot_reservation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slot_id uuid NOT NULL REFERENCES slot(id),
            appointment_id uuid NOT NULL REFERENCES appointment(id),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            state varchar(16) NOT NULL DEFAULT 'active',
            starts_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            period tstzrange GENERATED ALWAYS AS (tstzrange(starts_at, ends_at)) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_slot_reservation_state CHECK (state IN ('active','consumed','released')),
            CONSTRAINT ck_slot_reservation_window CHECK (ends_at > starts_at),
            CONSTRAINT ex_slot_reservation EXCLUDE USING gist (
                slot_id WITH =, period WITH &&) WHERE (state = 'active')
        );
        """
    )

    # Concorrência otimista: quem gravar com versão velha perde, e perde em voz alta.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_bump_appointment_version() RETURNS trigger AS $$
        BEGIN
            IF NEW.version <= OLD.version THEN
                RAISE EXCEPTION 'ERR_YARD_APPOINTMENT_STALE'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_appointment_version
            BEFORE UPDATE ON appointment
            FOR EACH ROW
            WHEN (OLD.* IS DISTINCT FROM NEW.*)
            EXECUTE FUNCTION yard_bump_appointment_version();
        """
    )

    # Janela fechada por parada de planta não aceita agendamento.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_check_plant_open() RETURNS trigger AS $$
        DECLARE blocked boolean;
        BEGIN
            IF NEW.state NOT IN ('confirmed','checked_in','in_progress') THEN
                RETURN NEW;
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM plant_stoppage s
                WHERE s.plant_id = NEW.plant_id
                  AND s.period && tstzrange(NEW.starts_at, NEW.ends_at)
            ) INTO blocked;
            IF blocked THEN
                RAISE EXCEPTION 'ERR_YARD_PLANT_STOPPAGE' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_appointment_plant_open
            BEFORE INSERT OR UPDATE ON appointment
            FOR EACH ROW EXECUTE FUNCTION yard_check_plant_open();
        """
    )

    # A visita passa a conhecer o agendamento que a originou.
    _exec("ALTER TABLE visit ADD COLUMN appointment_id uuid REFERENCES appointment(id)")


def downgrade() -> None:
    _exec(
        """
        ALTER TABLE visit DROP COLUMN IF EXISTS appointment_id;
        DROP TABLE IF EXISTS slot_reservation CASCADE;
        DROP TABLE IF EXISTS appointment_change_log CASCADE;
        DROP TABLE IF EXISTS appointment CASCADE;
        DROP SEQUENCE IF EXISTS appointment_reference_seq;
        DROP TABLE IF EXISTS priority_rule CASCADE;
        DROP TABLE IF EXISTS plant_stoppage CASCADE;
        DROP TABLE IF EXISTS shift_calendar CASCADE;
        DROP TABLE IF EXISTS resource CASCADE;
        DROP FUNCTION IF EXISTS yard_check_plant_open;
        DROP FUNCTION IF EXISTS yard_bump_appointment_version;
        """
    )
