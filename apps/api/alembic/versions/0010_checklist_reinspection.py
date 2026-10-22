"""Permite reinspeção de checklist e guarda o histórico da conferência.

Revision ID: 0010_checklist_reinspection
Create Date: 2026-09-21

O `UNIQUE (visit_id, item_id)` impedia responder um item duas vezes — ou seja, o guarda
reprovava "EPI incompleto", o motorista colocava o capacete, e **não havia como aprovar**:
o veículo ficava preso até alguém mexer no banco.

A correção não é sobrescrever a resposta: é aceitar várias no tempo e considerar a mais
recente. Quem audita precisa ver "reprovou 10:02, aprovou 10:15" — apagar a primeira
resposta apagaria justamente a informação que interessa.
"""

from app.core.migration_sql import exec_script as _exec

revision = "0010_checklist_reinspection"
down_revision = "0009_fix_move_confirmation_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        ALTER TABLE checklist_answer DROP CONSTRAINT IF EXISTS uq_checklist_answer;
        CREATE INDEX IF NOT EXISTS ix_checklist_answer_latest
            ON checklist_answer(visit_id, item_id, answered_at DESC);
        """
    )

    # O bloqueio acompanha a ÚLTIMA resposta de cada item: reprovou bloqueia,
    # reinspeção aprovada solta — sem precisar de alguém "destravando" na mão.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_checklist_block() RETURNS trigger AS $$
        DECLARE blocking_open integer;
        BEGIN
            SELECT count(*) INTO blocking_open
              FROM checklist_item i
              JOIN LATERAL (
                  SELECT a.passed
                    FROM checklist_answer a
                   WHERE a.visit_id = NEW.visit_id AND a.item_id = i.id
                   ORDER BY a.answered_at DESC
                   LIMIT 1
              ) last ON true
             WHERE i.severity = 'blocking' AND last.passed = false;

            IF blocking_open > 0 THEN
                UPDATE visit SET blocked_reason_code = 'CHECKLIST_FAILED'
                 WHERE id = NEW.visit_id AND blocked_reason_code IS NULL;
            ELSE
                -- Só limpa o que o próprio checklist pôs: pendência fiscal e divergência
                -- de peso continuam segurando o veículo.
                UPDATE visit SET blocked_reason_code = NULL
                 WHERE id = NEW.visit_id
                   AND blocked_reason_code = 'CHECKLIST_FAILED'
                   AND NOT EXISTS (
                       SELECT 1 FROM visit_hold h
                        WHERE h.visit_id = NEW.visit_id AND h.released_at IS NULL);
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP INDEX IF EXISTS ix_checklist_answer_latest;
        ALTER TABLE checklist_answer
            ADD CONSTRAINT uq_checklist_answer UNIQUE (visit_id, item_id);
        """
    )
