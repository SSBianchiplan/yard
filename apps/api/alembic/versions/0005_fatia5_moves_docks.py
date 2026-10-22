"""Fatia 5 — movimentação e doca: fila de manobrista, cronometria, divergência e bloqueio.

Revision ID: 0005_fatia5_moves_docks
Create Date: 2026-09-20

Invariantes que ficam no banco:
  - uma tarefa ativa por veículo                          (índice único parcial)
  - confirmação exige evidência (QR/RTLS/foto)            (CHECK)
  - evento offline é idempotente                          (índice único de client_event_id)
  - doca não recebe dois veículos ao mesmo tempo          (EXCLUDE)
  - etapas da doca respeitam a ordem do tempo             (CHECK)
  - divergência exige evidência fotográfica               (CHECK)
  - pendência aberta bloqueia a saída                     (trigger que marca a visita)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0005_fatia5_moves_docks"
down_revision = "0004_fatia4_gate_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE spotter (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(32) NOT NULL UNIQUE,
            full_name varchar(160) NOT NULL,
            shift_code varchar(32),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE move_task (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            reference varchar(24) NOT NULL UNIQUE,
            state varchar(16) NOT NULL DEFAULT 'proposed',
            visit_id uuid NOT NULL REFERENCES visit(id),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            from_slot_id uuid REFERENCES slot(id),
            to_slot_id uuid REFERENCES slot(id),
            from_dock_id uuid REFERENCES dock(id),
            to_dock_id uuid REFERENCES dock(id),
            spotter_id uuid REFERENCES spotter(id),
            priority_rank integer NOT NULL DEFAULT 500,
            cost_score numeric(8,2) NOT NULL DEFAULT 0,
            distance_m numeric(8,2),
            sla_deadline timestamptz,
            queued_at timestamptz,
            assigned_at timestamptz,
            accepted_at timestamptz,
            started_at timestamptz,
            confirmed_at timestamptz,
            cancelled_at timestamptz,
            confirmation_kind varchar(16),
            confirmation_value varchar(120),
            reason_code varchar(48),
            client_event_id varchar(64),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_move_state CHECK (state IN
                ('proposed','queued','assigned','accepted','in_progress','confirmed',
                 'cancelled','failed')),
            CONSTRAINT ck_move_target CHECK (to_slot_id IS NOT NULL OR to_dock_id IS NOT NULL),
            CONSTRAINT ck_move_priority CHECK (priority_rank > 0),
            -- confirmação por leitura, não por botão: manual exige motivo e vira exceção
            CONSTRAINT ck_move_confirmation CHECK (
                state <> 'confirmed'
                OR confirmation_kind IN ('qr','rtls','photo')
                OR (confirmation_kind = 'manual' AND reason_code IS NOT NULL)),
            CONSTRAINT ck_move_confirmation_kind CHECK (
                confirmation_kind IS NULL OR confirmation_kind IN ('qr','rtls','photo','manual')),
            CONSTRAINT ck_move_timeline CHECK (
                (accepted_at IS NULL OR assigned_at IS NULL OR accepted_at >= assigned_at)
                AND (started_at IS NULL OR accepted_at IS NULL OR started_at >= accepted_at)
                AND (confirmed_at IS NULL OR started_at IS NULL OR confirmed_at >= started_at))
        );
        -- um veículo tem no máximo uma tarefa viva
        CREATE UNIQUE INDEX uq_move_task_active ON move_task(vehicle_id)
            WHERE state IN ('queued','assigned','accepted','in_progress');
        -- PWA offline: o mesmo evento reenviado não vira tarefa nova
        CREATE UNIQUE INDEX uq_move_client_event ON move_task(client_event_id)
            WHERE client_event_id IS NOT NULL;
        CREATE INDEX ix_move_task_queue ON move_task(state, priority_rank, queued_at);
        CREATE SEQUENCE move_task_seq;

        CREATE TABLE move_deviation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            detected_at timestamptz NOT NULL DEFAULT now(),
            task_id uuid REFERENCES move_task(id),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            expected_slot_id uuid REFERENCES slot(id),
            actual_slot_id uuid REFERENCES slot(id),
            state varchar(16) NOT NULL DEFAULT 'open',
            corrective_task_id uuid REFERENCES move_task(id),
            CONSTRAINT ck_deviation_state CHECK (state IN ('open','corrected','accepted')),
            CONSTRAINT ck_deviation_slots CHECK (expected_slot_id IS DISTINCT FROM actual_slot_id)
        );
        """
    )

    _exec(
        """
        CREATE TABLE dock_visit (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dock_id uuid NOT NULL REFERENCES dock(id),
            visit_id uuid NOT NULL REFERENCES visit(id),
            appointment_id uuid REFERENCES appointment(id),
            state varchar(16) NOT NULL DEFAULT 'arrived',
            arrived_at timestamptz NOT NULL DEFAULT now(),
            docked_at timestamptz,
            started_at timestamptz,
            finished_at timestamptz,
            released_at timestamptz,
            paused_seconds integer NOT NULL DEFAULT 0,
            pause_reason_code varchar(48),
            paused_at timestamptz,
            period tstzrange GENERATED ALWAYS AS
                (tstzrange(arrived_at, released_at)) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_dock_visit_state CHECK (state IN
                ('scheduled','arrived','docked','started','paused','finished','released')),
            CONSTRAINT ck_dock_stage_order CHECK (
                (docked_at IS NULL OR docked_at >= arrived_at)
                AND (started_at IS NULL OR docked_at IS NULL OR started_at >= docked_at)
                AND (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
                AND (released_at IS NULL OR finished_at IS NULL OR released_at >= finished_at)),
            -- pausa sem motivo não vira análise de gargalo, vira desculpa
            CONSTRAINT ck_dock_pause_reason CHECK (
                state <> 'paused' OR pause_reason_code IS NOT NULL),
            CONSTRAINT ex_dock_visit EXCLUDE USING gist (dock_id WITH =, period WITH &&)
        );
        CREATE INDEX ix_dock_visit_visit ON dock_visit(visit_id);

        CREATE TABLE order_link (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            visit_id uuid NOT NULL REFERENCES visit(id),
            kind varchar(16) NOT NULL,
            external_id varchar(64) NOT NULL,
            quantity numeric(14,3),
            unit varchar(8),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_order_link_kind CHECK (kind IN
                ('production_order','purchase_order','sales_order','packing_list','transfer')),
            CONSTRAINT uq_order_link UNIQUE (visit_id, kind, external_id)
        );

        CREATE TABLE discrepancy (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dock_visit_id uuid NOT NULL REFERENCES dock_visit(id),
            reported_at timestamptz NOT NULL DEFAULT now(),
            kind varchar(24) NOT NULL,
            state varchar(16) NOT NULL DEFAULT 'open',
            quantity numeric(14,3),
            note varchar(400),
            evidence_ref varchar(240) NOT NULL,
            reported_by varchar(120) NOT NULL,
            reviewed_by varchar(120),
            CONSTRAINT ck_discrepancy_kind CHECK (kind IN
                ('damage','shortage','overage','temperature','humidity','seal_broken','other')),
            CONSTRAINT ck_discrepancy_state CHECK (state IN
                ('open','under_review','accepted','rejected')),
            CONSTRAINT ck_discrepancy_review CHECK (
                state NOT IN ('accepted','rejected') OR reviewed_by IS NOT NULL)
        );
        CREATE INDEX ix_discrepancy_dock_visit ON discrepancy(dock_visit_id);

        CREATE TABLE visit_hold (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            visit_id uuid NOT NULL REFERENCES visit(id),
            kind varchar(16) NOT NULL,
            reason_code varchar(48) NOT NULL,
            opened_at timestamptz NOT NULL DEFAULT now(),
            opened_by varchar(120) NOT NULL,
            released_at timestamptz,
            released_by varchar(120),
            note varchar(400),
            CONSTRAINT ck_hold_kind CHECK (kind IN ('quality','fiscal','safety','commercial')),
            CONSTRAINT ck_hold_release CHECK (
                released_at IS NULL OR released_by IS NOT NULL),
            -- quem abriu não é quem libera: segregação de função na prática
            CONSTRAINT ck_hold_segregation CHECK (
                released_by IS NULL OR released_by <> opened_by)
        );
        CREATE INDEX ix_visit_hold_open ON visit_hold(visit_id) WHERE released_at IS NULL;
        """
    )

    # Pendência aberta marca a visita; liberar a última pendência limpa o bloqueio.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_hold_sync_visit() RETURNS trigger AS $$
        DECLARE open_count integer;
        BEGIN
            SELECT count(*) INTO open_count FROM visit_hold
             WHERE visit_id = NEW.visit_id AND released_at IS NULL;
            IF open_count > 0 THEN
                UPDATE visit SET blocked_reason_code = NEW.reason_code
                 WHERE id = NEW.visit_id;
            ELSE
                UPDATE visit SET blocked_reason_code = NULL
                 WHERE id = NEW.visit_id
                   AND blocked_reason_code IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM weighing_ticket w
                        WHERE w.visit_id = NEW.visit_id AND w.state = 'closed'
                          AND w.divergence_pct IS NOT NULL
                          AND abs(w.divergence_pct) > w.tolerance_pct);
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_visit_hold_sync
            AFTER INSERT OR UPDATE ON visit_hold
            FOR EACH ROW EXECUTE FUNCTION yard_hold_sync_visit();
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP TABLE IF EXISTS visit_hold CASCADE;
        DROP TABLE IF EXISTS discrepancy CASCADE;
        DROP TABLE IF EXISTS order_link CASCADE;
        DROP TABLE IF EXISTS dock_visit CASCADE;
        DROP TABLE IF EXISTS move_deviation CASCADE;
        DROP TABLE IF EXISTS move_task CASCADE;
        DROP SEQUENCE IF EXISTS move_task_seq;
        DROP TABLE IF EXISTS spotter CASCADE;
        DROP FUNCTION IF EXISTS yard_hold_sync_visit;
        """
    )
