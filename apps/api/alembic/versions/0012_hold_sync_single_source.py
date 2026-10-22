"""Uma fonte de verdade para o bloqueio da visita: as pendências abertas.

Revision ID: 0012_hold_sync_single_source
Create Date: 2026-09-21

O gatilho de pendência só limpava o bloqueio se **também** não houvesse ticket com
divergência acima da tolerância. Fazia sentido quando a divergência escrevia direto em
`visit.blocked_reason_code`; depois da 0011 ela virou pendência — e a trava sobrou,
impedindo a liberação para sempre: o supervisor liberava a pendência e o veículo
continuava preso, sem nada na tela explicando por quê.

Agora é simples e verificável: **há pendência aberta → bloqueado; não há → livre.**
O ticket continua imutável e a divergência continua registrada; o que muda é que existe
um caminho auditado de volta.
"""

from app.core.migration_sql import exec_script as _exec

revision = "0012_hold_sync_single_source"
down_revision = "0011_weight_divergence_hold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_hold_sync_visit() RETURNS trigger AS $$
        DECLARE open_reason varchar(48);
        BEGIN
            SELECT h.reason_code INTO open_reason
              FROM visit_hold h
             WHERE h.visit_id = NEW.visit_id AND h.released_at IS NULL
             ORDER BY h.opened_at
             LIMIT 1;

            IF open_reason IS NOT NULL THEN
                UPDATE visit SET blocked_reason_code = open_reason
                 WHERE id = NEW.visit_id;
            ELSE
                -- Nenhuma pendência aberta: o checklist ainda pode estar segurando,
                -- e esse bloqueio tem gatilho próprio (yard_checklist_block).
                UPDATE visit SET blocked_reason_code = NULL
                 WHERE id = NEW.visit_id
                   AND blocked_reason_code IS DISTINCT FROM 'CHECKLIST_FAILED';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )

    # Destrava o que ficou presa pela regra antiga (pendência já liberada, visita não).
    _exec(
        """
        UPDATE visit v SET blocked_reason_code = NULL
         WHERE v.blocked_reason_code IS NOT NULL
           AND v.blocked_reason_code <> 'CHECKLIST_FAILED'
           AND NOT EXISTS (
               SELECT 1 FROM visit_hold h
                WHERE h.visit_id = v.id AND h.released_at IS NULL);
        """
    )


def downgrade() -> None:
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
                 WHERE id = NEW.visit_id AND blocked_reason_code IS NOT NULL;
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )
