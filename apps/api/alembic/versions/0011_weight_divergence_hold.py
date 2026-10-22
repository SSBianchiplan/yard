"""Divergência de peso passa a abrir pendência — e pendência tem como ser liberada.

Revision ID: 0011_weight_divergence_hold
Create Date: 2026-09-21

O trigger de pesagem escrevia direto em `visit.blocked_reason_code = 'WEIGHT_DIVERGENCE'`.
Bloqueava, como devia — mas **não havia caminho de volta**: nenhum endpoint limpa esse
campo, e o veículo ficava preso no pátio até alguém editar o banco. Em campo isso é
comum: o supervisor confere a divergência, aceita com justificativa (ou manda repesar) e
libera.

A correção é usar o mecanismo que já existe para isso — `visit_hold` — em vez de um
segundo jeito de bloquear. Um jeito de bloquear, um jeito de liberar, os dois auditados,
com a segregação de função valendo (quem abre não libera).
"""

from app.core.migration_sql import exec_script as _exec

revision = "0011_weight_divergence_hold"
down_revision = "0010_checklist_reinspection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_weighing_block_exit() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'closed' AND NEW.document_net_kg IS NOT NULL
               AND NEW.divergence_pct IS NOT NULL
               AND abs(NEW.divergence_pct) > NEW.tolerance_pct THEN
                -- Uma pendência por ticket: repesar não empilha bloqueio.
                IF NOT EXISTS (
                    SELECT 1 FROM visit_hold h
                     WHERE h.visit_id = NEW.visit_id
                       AND h.reason_code = 'WEIGHT_DIVERGENCE'
                       AND h.released_at IS NULL
                ) THEN
                    INSERT INTO visit_hold (
                        visit_id, kind, reason_code, opened_at, opened_by, note
                    )
                    VALUES (
                        NEW.visit_id,
                        'quality',
                        'WEIGHT_DIVERGENCE',
                        now(),
                        'system.weighing',
                        'ticket ' || NEW.reference || ': divergência de '
                            || NEW.divergence_pct || '% contra ' || NEW.document_number
                    );
                END IF;
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )

    # Migra o que já estava preso pelo caminho antigo, para não deixar veículo travado.
    _exec(
        """
        INSERT INTO visit_hold (visit_id, kind, reason_code, opened_at, opened_by, note)
        SELECT v.id, 'quality', 'WEIGHT_DIVERGENCE', now(), 'system.weighing',
               'pendência criada na migration 0011'
          FROM visit v
         WHERE v.blocked_reason_code = 'WEIGHT_DIVERGENCE'
           AND NOT EXISTS (
               SELECT 1 FROM visit_hold h
                WHERE h.visit_id = v.id AND h.reason_code = 'WEIGHT_DIVERGENCE'
                  AND h.released_at IS NULL);
        """
    )


def downgrade() -> None:
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
        """
    )
