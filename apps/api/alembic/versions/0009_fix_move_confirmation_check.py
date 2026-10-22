"""Aperta o CHECK de confirmação de manobra: NULL não pode passar batido.

Revision ID: 0009_fix_move_confirmation_check
Create Date: 2026-09-20

O CHECK original era:

    state <> 'confirmed'
    OR confirmation_kind IN ('qr','rtls','photo')
    OR (confirmation_kind = 'manual' AND reason_code IS NOT NULL)

Com `confirmation_kind` nulo, os dois últimos termos viram NULL e a expressão inteira
vira NULL — e CHECK só reprova quando o resultado é FALSE. Ou seja: dava para gravar
`state = 'confirmed'` sem evidência nenhuma, exatamente o que a regra existia para impedir.

Lógica de três valores é assim mesmo; a correção é tratar o nulo explicitamente.
Migration para a frente, sem editar a 0005 já aplicada.
"""

from app.core.migration_sql import exec_script as _exec

revision = "0009_fix_move_confirmation_check"
down_revision = "0008_fatia8_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        ALTER TABLE move_task DROP CONSTRAINT IF EXISTS ck_move_confirmation;
        ALTER TABLE move_task ADD CONSTRAINT ck_move_confirmation CHECK (
            state <> 'confirmed'
            OR COALESCE(confirmation_kind, '') IN ('qr','rtls','photo')
            OR (confirmation_kind = 'manual' AND reason_code IS NOT NULL)
        );
        """
    )

    # Mesma armadilha em `weighing_capture`: `source` é NOT NULL, então aqui o risco é
    # menor, mas a leitura fica explícita em vez de depender do NOT NULL para salvar.
    _exec(
        """
        ALTER TABLE weighing_capture DROP CONSTRAINT IF EXISTS ck_capture_valid;
        ALTER TABLE weighing_capture ADD CONSTRAINT ck_capture_valid CHECK (
            COALESCE(source, '') = 'manual'
            OR (COALESCE(stable, false) = true AND COALESCE(vehicle_positioned, false) = true)
        );
        """
    )


def downgrade() -> None:
    _exec(
        """
        ALTER TABLE move_task DROP CONSTRAINT IF EXISTS ck_move_confirmation;
        ALTER TABLE move_task ADD CONSTRAINT ck_move_confirmation CHECK (
            state <> 'confirmed'
            OR confirmation_kind IN ('qr','rtls','photo')
            OR (confirmation_kind = 'manual' AND reason_code IS NOT NULL)
        );
        ALTER TABLE weighing_capture DROP CONSTRAINT IF EXISTS ck_capture_valid;
        ALTER TABLE weighing_capture ADD CONSTRAINT ck_capture_valid CHECK (
            source = 'manual' OR (stable = true AND vehicle_positioned = true)
        );
        """
    )
