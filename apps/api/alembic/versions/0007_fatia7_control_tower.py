"""Fatia 7 — torre de controle e IA: proposta, aprovação humana e execução rastreada.

Revision ID: 0007_fatia7_control_tower
Create Date: 2026-09-20

O invariante que define o produto:
    **nenhum comando físico nasce de sugestão não aprovada.**

Ele mora em três lugares que se reforçam:
  - `ai_proposal` só sai de `proposed` com `approved_by` preenchido        (CHECK)
  - proposta expirada não executa                                          (CHECK)
  - `access_command.origin = 'ai'` exige `approved_by`                     (CHECK, Fatia 4)
  - a FK de `access_command.ai_proposal_id` passa a apontar para a proposta (FK)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0007_fatia7_control_tower"
down_revision = "0006_fatia6_iot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE ai_proposal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            reference varchar(24) NOT NULL UNIQUE,
            kind varchar(32) NOT NULL,
            state varchar(16) NOT NULL DEFAULT 'proposed',
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            rationale varchar(600) NOT NULL,
            impact_json jsonb NOT NULL,
            payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            confidence numeric(4,3),
            model_version varchar(48),
            reviewed_by varchar(120),
            reviewed_at timestamptz,
            approved_by varchar(120),
            approved_at timestamptz,
            rejected_reason_code varchar(48),
            executed_at timestamptz,
            execution_result varchar(240),
            CONSTRAINT ck_ai_kind CHECK (kind IN
                ('dock_resequence','slot_reassign','queue_priority','dwell_alert',
                 'release_forecast','gate_command')),
            CONSTRAINT ck_ai_state CHECK (state IN
                ('proposed','under_review','approved','executing','executed','rejected',
                 'expired')),
            -- nada sai de 'proposed' sem um humano identificado
            CONSTRAINT ck_ai_approval CHECK (
                state NOT IN ('approved','executing','executed')
                OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
            -- proposta velha não executa: pátio muda rápido demais
            CONSTRAINT ck_ai_expiry CHECK (state <> 'executing' OR expires_at > now()),
            CONSTRAINT ck_ai_rejected CHECK (
                state <> 'rejected' OR rejected_reason_code IS NOT NULL),
            -- proposta sem impacto calculado é palpite, e palpite não vai para a tela
            CONSTRAINT ck_ai_impact CHECK (jsonb_typeof(impact_json) = 'object'),
            CONSTRAINT ck_ai_confidence CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        );
        CREATE INDEX ix_ai_proposal_state ON ai_proposal(state, created_at DESC);
        CREATE SEQUENCE ai_proposal_seq;

        CREATE TABLE human_decision (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id uuid NOT NULL REFERENCES ai_proposal(id),
            decided_at timestamptz NOT NULL DEFAULT now(),
            decided_by varchar(120) NOT NULL,
            decision varchar(16) NOT NULL,
            reason_code varchar(48),
            note varchar(400),
            CONSTRAINT ck_decision CHECK (decision IN ('approved','rejected','edited'))
        );
        CREATE INDEX ix_human_decision_proposal ON human_decision(proposal_id, decided_at);

        CREATE TABLE release_forecast (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            visit_id uuid NOT NULL REFERENCES visit(id),
            predicted_release_at timestamptz NOT NULL,
            confidence numeric(4,3),
            model_version varchar(48),
            actual_release_at timestamptz,
            error_minutes integer,
            PRIMARY KEY (id, occurred_at)
        );
        CREATE INDEX ix_release_forecast_visit ON release_forecast(visit_id, occurred_at DESC);

        CREATE TABLE bottleneck_signal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            detected_at timestamptz NOT NULL DEFAULT now(),
            scope varchar(24) NOT NULL,
            scope_ref varchar(48),
            severity varchar(16) NOT NULL DEFAULT 'medium',
            metric varchar(48) NOT NULL,
            value numeric(12,2) NOT NULL,
            threshold numeric(12,2) NOT NULL,
            state varchar(16) NOT NULL DEFAULT 'open',
            acknowledged_by varchar(120),
            acknowledged_at timestamptz,
            CONSTRAINT ck_bottleneck_scope CHECK (scope IN ('gate','dock','zone','scale','yard')),
            CONSTRAINT ck_bottleneck_severity CHECK (severity IN
                ('critical','high','medium','low')),
            CONSTRAINT ck_bottleneck_state CHECK (state IN
                ('open','acknowledged','shelved','closed')),
            -- ISA-18.2: reconhecer é ato de alguém, com hora
            CONSTRAINT ck_bottleneck_ack CHECK (
                state <> 'acknowledged'
                OR (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL))
        );
        CREATE INDEX ix_bottleneck_open ON bottleneck_signal(state, severity, detected_at DESC);
        """
    )

    # O comando físico passa a referenciar formalmente a proposta que o originou.
    _exec(
        """
        ALTER TABLE access_command
            ADD CONSTRAINT fk_access_command_ai_proposal
            FOREIGN KEY (ai_proposal_id) REFERENCES ai_proposal(id);
        """
    )

    # Execução só com proposta aprovada, não expirada e decisão humana registrada.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_ai_execution_guard() RETURNS trigger AS $$
        DECLARE p record;
        BEGIN
            IF NEW.ai_proposal_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT state, expires_at, approved_by INTO p
              FROM ai_proposal WHERE id = NEW.ai_proposal_id;
            IF p.approved_by IS NULL OR p.state NOT IN ('approved','executing','executed') THEN
                RAISE EXCEPTION 'ERR_YARD_COMMAND_AI_NOT_APPROVED'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF p.expires_at <= now() THEN
                RAISE EXCEPTION 'ERR_YARD_AI_PROPOSAL_EXPIRED' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_access_command_ai_guard
            BEFORE INSERT ON access_command
            FOR EACH ROW EXECUTE FUNCTION yard_ai_execution_guard();
        """
    )

    # Toda decisão humana sobre IA é append-only: é dado de auditoria e de treino.
    _exec(
        """
        CREATE TRIGGER trg_human_decision_append_only
            BEFORE UPDATE OR DELETE ON human_decision
            FOR EACH ROW EXECUTE FUNCTION yard_deny_mutation();
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP TRIGGER IF EXISTS trg_access_command_ai_guard ON access_command;
        ALTER TABLE access_command DROP CONSTRAINT IF EXISTS fk_access_command_ai_proposal;
        DROP TABLE IF EXISTS bottleneck_signal CASCADE;
        DROP TABLE IF EXISTS release_forecast CASCADE;
        DROP TABLE IF EXISTS human_decision CASCADE;
        DROP TABLE IF EXISTS ai_proposal CASCADE;
        DROP SEQUENCE IF EXISTS ai_proposal_seq;
        DROP FUNCTION IF EXISTS yard_ai_execution_guard;
        """
    )
