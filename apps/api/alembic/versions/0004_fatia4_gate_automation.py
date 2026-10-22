"""Fatia 4 — automação de portaria: LPR, QR, RFID, checklist, triagem e comando físico.

Revision ID: 0004_fatia4_gate_automation
Create Date: 2026-09-20

Invariantes que ficam no banco:
  - comando físico só sai com permissivo do CLP e autorizador       (CHECK)
  - comando de origem IA exige aprovação humana registrada          (CHECK)
  - identificação abaixo do limiar não vira liberação automática    (CHECK)
  - checklist reprovado em item bloqueante não deixa liberar        (CHECK + trigger)
  - evento de identificação e comando são append-only               (trigger)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0004_fatia4_gate_automation"
down_revision = "0003_fatia3_weighing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE device (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(48) NOT NULL UNIQUE,
            kind varchar(32) NOT NULL,
            gate_id uuid REFERENCES gate(id),
            dock_id uuid REFERENCES dock(id),
            scale_id uuid REFERENCES scale(id),
            protocol varchar(24) NOT NULL DEFAULT 'simulator',
            endpoint varchar(160),
            status varchar(16) NOT NULL DEFAULT 'online',
            last_seen_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_device_kind CHECK (kind IN
                ('barrier','traffic_light','loop_detector','photocell','rfid_reader',
                 'lpr_camera','scale_indicator','hopper_level','push_button','plc',
                 'kiosk','gate_display')),
            CONSTRAINT ck_device_status CHECK (status IN
                ('online','degraded','offline','maintenance')),
            CONSTRAINT ck_device_protocol CHECK (protocol IN
                ('simulator','mqtt_sparkplug','opcua','modbus_tcp','http','serial'))
        );
        CREATE INDEX ix_device_gate ON device(gate_id);

        CREATE TABLE identification_event (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            gate_id uuid NOT NULL REFERENCES gate(id),
            device_id uuid REFERENCES device(id),
            method varchar(16) NOT NULL,
            raw_value varchar(120),
            normalized_value varchar(64),
            confidence numeric(4,3),
            matched_vehicle_id uuid REFERENCES vehicle(id),
            matched_appointment_id uuid REFERENCES appointment(id),
            visit_id uuid REFERENCES visit(id),
            state varchar(24) NOT NULL DEFAULT 'captured',
            image_ref varchar(240),
            actor varchar(120),
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT ck_identification_method CHECK (method IN
                ('lpr','qr','rfid','badge','manual','whatsapp')),
            CONSTRAINT ck_identification_state CHECK (state IN
                ('captured','matched','ambiguous','manual_override','rejected')),
            CONSTRAINT ck_identification_confidence CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            -- leitura automática só "casa" sozinha acima do limiar; abaixo disso é humano
            CONSTRAINT ck_identification_threshold CHECK (
                state <> 'matched' OR method <> 'lpr' OR confidence >= 0.85),
            CONSTRAINT ck_identification_manual CHECK (
                method <> 'manual' OR actor IS NOT NULL)
        );
        CREATE INDEX ix_identification_gate ON identification_event(gate_id, occurred_at DESC);

        DO $$ BEGIN
            PERFORM create_hypertable('identification_event','occurred_at',
                     chunk_time_interval => interval '7 days', migrate_data => true);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'identification_event permanece tabela comum';
        END $$;
        """
    )

    _exec(
        """
        CREATE TABLE checklist_template (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(48) NOT NULL UNIQUE,
            direction varchar(16) NOT NULL DEFAULT 'in',
            operation_type_id uuid REFERENCES operation_type(id),
            hazardous_only boolean NOT NULL DEFAULT false,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_checklist_direction CHECK (direction IN ('in','out','both'))
        );

        CREATE TABLE checklist_item (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id uuid NOT NULL REFERENCES checklist_template(id),
            code varchar(48) NOT NULL,
            position integer NOT NULL,
            severity varchar(16) NOT NULL DEFAULT 'blocking',
            requires_photo boolean NOT NULL DEFAULT false,
            CONSTRAINT ck_checklist_severity CHECK (severity IN ('blocking','warning','info')),
            CONSTRAINT uq_checklist_item UNIQUE (template_id, code)
        );

        CREATE TABLE checklist_answer (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            visit_id uuid NOT NULL REFERENCES visit(id),
            item_id uuid NOT NULL REFERENCES checklist_item(id),
            answered_at timestamptz NOT NULL DEFAULT now(),
            passed boolean NOT NULL,
            note varchar(240),
            photo_ref varchar(240),
            actor varchar(120) NOT NULL,
            CONSTRAINT uq_checklist_answer UNIQUE (visit_id, item_id)
        );
        CREATE INDEX ix_checklist_answer_visit ON checklist_answer(visit_id);
        """
    )

    _exec(
        """
        CREATE TABLE access_command (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            requested_at timestamptz NOT NULL DEFAULT now(),
            device_id uuid NOT NULL REFERENCES device(id),
            gate_id uuid REFERENCES gate(id),
            visit_id uuid REFERENCES visit(id),
            action varchar(24) NOT NULL,
            state varchar(24) NOT NULL DEFAULT 'requested',
            origin varchar(16) NOT NULL DEFAULT 'human',
            plc_permissive boolean,
            permissive_quality varchar(16),
            authorized_by varchar(120),
            approved_by varchar(120),
            approved_at timestamptz,
            ai_proposal_id uuid,
            reason_code varchar(48),
            acknowledged_at timestamptz,
            failure_code varchar(48),
            CONSTRAINT ck_command_action CHECK (action IN
                ('open_barrier','close_barrier','green_light','red_light','open_gate',
                 'display_message','lock_dock','unlock_dock')),
            CONSTRAINT ck_command_state CHECK (state IN
                ('requested','permitted','sent','acknowledged','failed','denied_by_plc',
                 'timeout')),
            CONSTRAINT ck_command_origin CHECK (origin IN ('human','system','ai','self_service')),
            -- comando físico só sai com permissivo verdadeiro E autorizador identificado
            CONSTRAINT ck_command_permissive CHECK (
                state NOT IN ('sent','acknowledged')
                OR (plc_permissive = true AND authorized_by IS NOT NULL)),
            -- permissivo obsoleto ou sem comunicação não vale como permissivo
            CONSTRAINT ck_command_permissive_quality CHECK (
                state NOT IN ('sent','acknowledged') OR permissive_quality = 'good'),
            -- interlock: comando vindo de IA exige aprovação humana registrada
            CONSTRAINT ck_command_ai_approval CHECK (
                origin <> 'ai' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
        );
        CREATE INDEX ix_access_command_gate ON access_command(gate_id, requested_at DESC);
        CREATE INDEX ix_access_command_visit ON access_command(visit_id);

        CREATE TABLE escort (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            visit_id uuid NOT NULL REFERENCES visit(id),
            full_name varchar(160) NOT NULL,
            document varchar(32) NOT NULL,
            role varchar(24) NOT NULL DEFAULT 'helper',
            entered_at timestamptz NOT NULL DEFAULT now(),
            exited_at timestamptz,
            CONSTRAINT ck_escort_role CHECK (role IN ('helper','visitor','contractor','driver')),
            CONSTRAINT ck_escort_period CHECK (exited_at IS NULL OR exited_at >= entered_at)
        );
        CREATE INDEX ix_escort_visit ON escort(visit_id);
        """
    )

    # Trilha de comando é append-only: alterar comando emitido é reescrever a história.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_command_no_rewrite() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ERR_YARD_AUDIT_IMMUTABLE' USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.state IN ('acknowledged','failed','denied_by_plc','timeout') THEN
                RAISE EXCEPTION 'ERR_YARD_AUDIT_IMMUTABLE' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_access_command_append_only
            BEFORE UPDATE OR DELETE ON access_command
            FOR EACH ROW EXECUTE FUNCTION yard_command_no_rewrite();

        CREATE TRIGGER trg_identification_append_only
            BEFORE UPDATE OR DELETE ON identification_event
            FOR EACH ROW EXECUTE FUNCTION yard_deny_mutation();
        """
    )

    # Checklist reprovado em item bloqueante impede liberar o veículo para o pátio.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_checklist_block() RETURNS trigger AS $$
        BEGIN
            IF NEW.passed = false THEN
                IF EXISTS (
                    SELECT 1 FROM checklist_item i
                    WHERE i.id = NEW.item_id AND i.severity = 'blocking'
                ) THEN
                    UPDATE visit SET blocked_reason_code = 'CHECKLIST_FAILED'
                     WHERE id = NEW.visit_id AND blocked_reason_code IS NULL;
                END IF;
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_checklist_block
            AFTER INSERT OR UPDATE ON checklist_answer
            FOR EACH ROW EXECUTE FUNCTION yard_checklist_block();
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP TABLE IF EXISTS escort CASCADE;
        DROP TABLE IF EXISTS access_command CASCADE;
        DROP TABLE IF EXISTS checklist_answer CASCADE;
        DROP TABLE IF EXISTS checklist_item CASCADE;
        DROP TABLE IF EXISTS checklist_template CASCADE;
        DROP TABLE IF EXISTS identification_event CASCADE;
        DROP TABLE IF EXISTS device CASCADE;
        DROP FUNCTION IF EXISTS yard_checklist_block;
        DROP FUNCTION IF EXISTS yard_command_no_rewrite;
        """
    )
