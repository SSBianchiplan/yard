"""Fatia 3 — balança: leitura de indicador, ticket bruto/tara/líquido, antifraude.

Revision ID: 0003_fatia3_weighing
Create Date: 2026-09-20

Invariantes que ficam no banco:
  - ticket fechado é imutável                      (trigger)
  - líquido = bruto − tara, sempre                 (CHECK)
  - ticket fechado tem hash e imagem               (CHECK)
  - pesagem manual exige motivo e segundo fator    (CHECK)
  - divergência fora da tolerância bloqueia saída  (trigger que marca a visita)
  - reimpressão é contada, nunca silenciosa        (CHECK + tabela de auditoria)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0003_fatia3_weighing"
down_revision = "0002_fatia2_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        ALTER TABLE scale ADD COLUMN protocol varchar(24) NOT NULL DEFAULT 'simulator';
        ALTER TABLE scale ADD COLUMN endpoint varchar(120);
        ALTER TABLE scale ADD COLUMN division_kg integer NOT NULL DEFAULT 20;
        ALTER TABLE scale ADD COLUMN stability_window_seconds integer NOT NULL DEFAULT 3;
        ALTER TABLE scale ADD COLUMN stability_tolerance_kg integer NOT NULL DEFAULT 20;
        ALTER TABLE scale ADD COLUMN status varchar(16) NOT NULL DEFAULT 'online';
        ALTER TABLE scale ADD CONSTRAINT ck_scale_protocol CHECK (protocol IN
            ('simulator','serial_toledo','serial_filizola','tcp_toledo','tcp_generic','opcua'));
        ALTER TABLE scale ADD CONSTRAINT ck_scale_status CHECK (status IN
            ('online','degraded','offline','maintenance'));

        ALTER TABLE vehicle ADD COLUMN tare_source varchar(16) NOT NULL DEFAULT 'registered';
        ALTER TABLE vehicle ADD CONSTRAINT ck_vehicle_tare_source CHECK (tare_source IN
            ('registered','measured'));
        """
    )

    _exec(
        """
        CREATE TABLE scale_reading (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            scale_id uuid NOT NULL REFERENCES scale(id),
            weight_kg integer NOT NULL,
            stable boolean NOT NULL DEFAULT false,
            quality varchar(16) NOT NULL DEFAULT 'good',
            vehicle_positioned boolean,
            source varchar(24) NOT NULL DEFAULT 'device',
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT ck_scale_reading_quality CHECK (quality IN
                ('good','stale','invalid','no_comm')),
            CONSTRAINT ck_scale_reading_weight CHECK (weight_kg >= 0)
        );
        CREATE INDEX ix_scale_reading_scale ON scale_reading(scale_id, occurred_at DESC);

        DO $$ BEGIN
            PERFORM create_hypertable('scale_reading','occurred_at',
                     chunk_time_interval => interval '1 day', migrate_data => true);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'scale_reading permanece tabela comum';
        END $$;
        """
    )

    _exec(
        """
        CREATE SEQUENCE weighing_ticket_seq;

        CREATE TABLE weighing_ticket (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            reference varchar(24) NOT NULL UNIQUE,
            state varchar(16) NOT NULL DEFAULT 'open',
            visit_id uuid NOT NULL REFERENCES visit(id),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            scale_id uuid NOT NULL REFERENCES scale(id),
            product_id uuid REFERENCES product(id),
            mode varchar(16) NOT NULL DEFAULT 'double',
            gross_kg integer,
            tare_kg integer,
            net_kg integer,
            tare_source varchar(16),
            gross_at timestamptz,
            tare_at timestamptz,
            closed_at timestamptz,
            document_number varchar(64),
            document_net_kg integer,
            divergence_kg integer,
            divergence_pct numeric(6,3),
            tolerance_pct numeric(6,3) NOT NULL DEFAULT 0.5,
            source varchar(16) NOT NULL DEFAULT 'device',
            reason_code varchar(48),
            operator varchar(120),
            second_factor_user varchar(120),
            image_ref varchar(240),
            integrity_hash varchar(64),
            reprint_count integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_weighing_state CHECK (state IN
                ('open','first_weight','second_weight','closed','cancelled')),
            CONSTRAINT ck_weighing_mode CHECK (mode IN ('double','fixed_tare','axle')),
            CONSTRAINT ck_weighing_source CHECK (source IN ('device','manual','simulator')),
            CONSTRAINT ck_weighing_positive CHECK (
                (gross_kg IS NULL OR gross_kg > 0) AND (tare_kg IS NULL OR tare_kg > 0)),
            -- líquido é derivado, nunca digitado
            CONSTRAINT ck_weighing_net CHECK (
                net_kg IS NULL OR (gross_kg IS NOT NULL AND tare_kg IS NOT NULL
                                   AND net_kg = gross_kg - tare_kg)),
            CONSTRAINT ck_weighing_gross_ge_tare CHECK (
                gross_kg IS NULL OR tare_kg IS NULL OR gross_kg >= tare_kg),
            -- pesagem manual exige justificativa E segundo fator
            CONSTRAINT ck_weighing_manual CHECK (
                source <> 'manual' OR (reason_code IS NOT NULL AND second_factor_user IS NOT NULL)),
            -- ticket fechado carrega hash de integridade e imagem do instante do peso
            CONSTRAINT ck_weighing_closed CHECK (
                state <> 'closed' OR (integrity_hash IS NOT NULL AND image_ref IS NOT NULL
                                      AND net_kg IS NOT NULL AND closed_at IS NOT NULL)),
            CONSTRAINT ck_weighing_reprint CHECK (reprint_count >= 0),
            CONSTRAINT ck_weighing_cancel CHECK (state <> 'cancelled' OR reason_code IS NOT NULL)
        );
        CREATE INDEX ix_weighing_ticket_visit ON weighing_ticket(visit_id);
        CREATE UNIQUE INDEX uq_weighing_open_visit ON weighing_ticket(visit_id)
            WHERE state IN ('open','first_weight','second_weight');

        CREATE TABLE weighing_capture (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ticket_id uuid NOT NULL REFERENCES weighing_ticket(id),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            kind varchar(16) NOT NULL,
            weight_kg integer NOT NULL,
            stable boolean NOT NULL,
            vehicle_positioned boolean NOT NULL,
            image_ref varchar(240),
            operator varchar(120),
            source varchar(16) NOT NULL DEFAULT 'device',
            CONSTRAINT ck_capture_kind CHECK (kind IN ('gross','tare','axle')),
            -- captura só vale com peso estável e veículo posicionado; exceção é manual
            CONSTRAINT ck_capture_valid CHECK (
                source = 'manual' OR (stable = true AND vehicle_positioned = true))
        );
        CREATE INDEX ix_weighing_capture_ticket ON weighing_capture(ticket_id, occurred_at);

        CREATE TABLE axle_weight (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ticket_id uuid NOT NULL REFERENCES weighing_ticket(id),
            axle_number smallint NOT NULL,
            weight_kg integer NOT NULL,
            CONSTRAINT ck_axle_number CHECK (axle_number BETWEEN 1 AND 12),
            CONSTRAINT ck_axle_weight CHECK (weight_kg > 0),
            CONSTRAINT uq_axle_per_ticket UNIQUE (ticket_id, axle_number)
        );

        CREATE TABLE weighing_reprint (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ticket_id uuid NOT NULL REFERENCES weighing_ticket(id),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            actor varchar(120) NOT NULL,
            reason_code varchar(48) NOT NULL
        );

        CREATE TABLE tare_record (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            measured_at timestamptz NOT NULL DEFAULT now(),
            tare_kg integer NOT NULL,
            scale_id uuid REFERENCES scale(id),
            ticket_id uuid REFERENCES weighing_ticket(id),
            CONSTRAINT ck_tare_record_positive CHECK (tare_kg > 0)
        );
        CREATE INDEX ix_tare_record_vehicle ON tare_record(vehicle_id, measured_at DESC);
        """
    )

    # Ticket fechado é imutável: correção é ticket novo, com rastro do anterior.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_weighing_immutable() RETURNS trigger AS $$
        BEGIN
            -- reimpressão é a única coluna que pode mudar depois do fechamento
            IF (NEW.reprint_count IS DISTINCT FROM OLD.reprint_count)
               AND (to_jsonb(NEW) - 'reprint_count' - 'updated_at')
                 = (to_jsonb(OLD) - 'reprint_count' - 'updated_at') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'ERR_YARD_TICKET_IMMUTABLE' USING ERRCODE = 'check_violation';
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_weighing_ticket_immutable
            BEFORE UPDATE OR DELETE ON weighing_ticket
            FOR EACH ROW WHEN (OLD.state = 'closed')
            EXECUTE FUNCTION yard_weighing_immutable();
        """
    )

    # Divergência peso × documento fiscal acima da tolerância bloqueia a saída na hora.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_weighing_block_exit() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'closed' AND NEW.document_net_kg IS NOT NULL
               AND NEW.divergence_pct IS NOT NULL
               AND abs(NEW.divergence_pct) > NEW.tolerance_pct THEN
                UPDATE visit SET blocked_reason_code = 'WEIGHT_DIVERGENCE'
                 WHERE id = NEW.visit_id AND blocked_reason_code IS NULL;
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_weighing_block_exit
            AFTER INSERT OR UPDATE ON weighing_ticket
            FOR EACH ROW EXECUTE FUNCTION yard_weighing_block_exit();
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP TABLE IF EXISTS tare_record CASCADE;
        DROP TABLE IF EXISTS weighing_reprint CASCADE;
        DROP TABLE IF EXISTS axle_weight CASCADE;
        DROP TABLE IF EXISTS weighing_capture CASCADE;
        DROP TABLE IF EXISTS weighing_ticket CASCADE;
        DROP SEQUENCE IF EXISTS weighing_ticket_seq;
        DROP TABLE IF EXISTS scale_reading CASCADE;
        DROP FUNCTION IF EXISTS yard_weighing_block_exit;
        DROP FUNCTION IF EXISTS yard_weighing_immutable;
        ALTER TABLE vehicle DROP COLUMN IF EXISTS tare_source;
        ALTER TABLE scale DROP COLUMN IF EXISTS status;
        ALTER TABLE scale DROP COLUMN IF EXISTS stability_tolerance_kg;
        ALTER TABLE scale DROP COLUMN IF EXISTS stability_window_seconds;
        ALTER TABLE scale DROP COLUMN IF EXISTS division_kg;
        ALTER TABLE scale DROP COLUMN IF EXISTS endpoint;
        ALTER TABLE scale DROP COLUMN IF EXISTS protocol;
        """
    )
