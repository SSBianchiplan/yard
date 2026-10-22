"""Chave de acesso do portal por transportadora.

Revision ID: 0014_carrier_portal_key
Create Date: 2026-10-22

Auditoria 2026-10 (A7): o portal identificava a transportadora só pelo cabeçalho
`X-Carrier-Code` — quem soubesse o código (está em nota, em placa de caminhão, em e-mail)
listava e criava agendamentos em nome dela. Agora cada transportadora tem uma chave
própria, gerada pela planta e mostrada uma vez; o banco guarda só o SHA-256 dela.

Aditiva e reversível: duas colunas nulas, nenhuma linha reescrita.
"""

from app.core.migration_sql import exec_script as _exec

revision = "0014_carrier_portal_key"
down_revision = "0013_users_and_yard_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        ALTER TABLE carrier
            ADD COLUMN portal_key_hash char(64),
            ADD COLUMN portal_key_issued_at timestamptz;
        CREATE UNIQUE INDEX uq_carrier_portal_key_hash
            ON carrier (portal_key_hash) WHERE portal_key_hash IS NOT NULL;
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP INDEX IF EXISTS uq_carrier_portal_key_hash;
        ALTER TABLE carrier
            DROP COLUMN IF EXISTS portal_key_issued_at,
            DROP COLUMN IF EXISTS portal_key_hash;
        """
    )
