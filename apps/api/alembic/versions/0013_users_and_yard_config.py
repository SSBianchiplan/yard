"""Usuários locais, trilha de acesso e cadastro de pátio editável.

Revision ID: 0013_users_and_yard_config
Create Date: 2026-09-26

Até aqui a identidade vinha do Keycloak ou de um cabeçalho de desenvolvimento. Para
instalação sem Keycloak, os usuários moram no próprio Postgres (`YARD_AUTH_MODE=local`).

Invariantes no banco:
  - e-mail único sem distinção de caixa (índice em lower(email)) e já gravado minúsculo;
  - perfil só dos conhecidos — perfil digitado errado é permissão que não existe;
  - o admin master não se desativa, não perde `yard.admin` e não é apagado; e sempre
    existe no máximo um (índice parcial) — "ninguém mais consegue administrar" não pode
    ser um estado alcançável por um clique;
  - `auth_audit` é append-only, como `visit_event`.

Pátio: `plant` ganha segmento, cidade, descrição e ativo — o cadastro de um novo pátio
deixa de ser tarefa de seed e passa a ser tela. Zona e vaga ganham o tipo `cold_chain`
(alimentos) e zona/doca passam a ter o tipo checado no banco, como a vaga já tinha.
"""

from app.core.migration_sql import exec_script as _exec

revision = "0013_users_and_yard_config"
down_revision = "0012_hold_sync_single_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE app_user (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            email varchar(254) NOT NULL,
            name varchar(160) NOT NULL,
            password_hash varchar(255) NOT NULL,
            roles varchar(32)[] NOT NULL DEFAULT '{}',
            active boolean NOT NULL DEFAULT true,
            is_master boolean NOT NULL DEFAULT false,
            must_change_password boolean NOT NULL DEFAULT true,
            failed_logins integer NOT NULL DEFAULT 0,
            locked_until timestamptz,
            last_login_at timestamptz,
            password_changed_at timestamptz,
            created_by varchar(254),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_app_user_email_lower CHECK (email = lower(email) AND position('@' in email) > 1),
            CONSTRAINT ck_app_user_roles_known CHECK (roles <@ ARRAY[
                'yard.scheduler','yard.gate','yard.scale','yard.spotter','yard.dock',
                'yard.supervisor','yard.controller','yard.admin','yard.device'
            ]::varchar(32)[]),
            -- master é sempre admin e sempre ativo
            CONSTRAINT ck_app_user_master_admin CHECK (
                NOT is_master OR (active AND 'yard.admin' = ANY(roles)))
        );
        CREATE UNIQUE INDEX uq_app_user_email ON app_user (lower(email));
        CREATE UNIQUE INDEX uq_app_user_single_master ON app_user (is_master) WHERE is_master;

        CREATE OR REPLACE FUNCTION yard_user_protect_master() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.is_master THEN
                RAISE EXCEPTION 'ERR_AUTH_MASTER_PROTECTED' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.is_master AND NOT NEW.is_master THEN
                RAISE EXCEPTION 'ERR_AUTH_MASTER_PROTECTED' USING ERRCODE = 'check_violation';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_app_user_protect_master
            BEFORE UPDATE OR DELETE ON app_user
            FOR EACH ROW EXECUTE FUNCTION yard_user_protect_master();

        CREATE TABLE auth_audit (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            event_type varchar(32) NOT NULL,
            actor varchar(254),
            target_email varchar(254),
            ip varchar(64),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX ix_auth_audit_occurred ON auth_audit (occurred_at DESC);

        CREATE OR REPLACE FUNCTION yard_auth_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ERR_YARD_AUDIT_IMMUTABLE' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_auth_audit_immutable
            BEFORE UPDATE OR DELETE ON auth_audit
            FOR EACH ROW EXECUTE FUNCTION yard_auth_audit_immutable();

        ALTER TABLE plant ADD COLUMN segment varchar(32) NOT NULL DEFAULT 'general';
        ALTER TABLE plant ADD COLUMN city varchar(120);
        ALTER TABLE plant ADD COLUMN description text;
        ALTER TABLE plant ADD COLUMN active boolean NOT NULL DEFAULT true;
        ALTER TABLE plant ADD CONSTRAINT ck_plant_segment CHECK (
            segment IN ('general','food','beverage','chemical','steel','automotive','logistics','agro'));
        -- geometria sempre positiva: largura/altura zero é elemento invisível no mapa
        ALTER TABLE zone ADD CONSTRAINT ck_zone_positive_size CHECK (width > 0 AND height > 0);
        ALTER TABLE slot ADD CONSTRAINT ck_slot_positive_size CHECK (width > 0 AND height > 0);
        ALTER TABLE dock ADD CONSTRAINT ck_dock_positive_size CHECK (width > 0 AND height > 0);
        -- alimentos: vaga de cadeia fria (tomada para o baú refrigerado) é tipo próprio
        ALTER TABLE slot DROP CONSTRAINT ck_slot_kind;
        ALTER TABLE slot ADD CONSTRAINT ck_slot_kind CHECK (kind IN (
            'parking','staging','quarantine','scale_queue','dock_approach','cold_chain'));
        ALTER TABLE zone ADD CONSTRAINT ck_zone_kind CHECK (kind IN (
            'parking','staging','quarantine','scale_queue','dock_approach','cold_chain'));
        ALTER TABLE dock ADD CONSTRAINT ck_dock_direction CHECK (
            direction IN ('inbound','outbound','both'))
        """
    )


def downgrade() -> None:
    _exec(
        """
        ALTER TABLE dock DROP CONSTRAINT IF EXISTS ck_dock_direction;
        ALTER TABLE zone DROP CONSTRAINT IF EXISTS ck_zone_kind;
        ALTER TABLE slot DROP CONSTRAINT ck_slot_kind;
        ALTER TABLE slot ADD CONSTRAINT ck_slot_kind CHECK (kind IN (
            'parking','staging','quarantine','scale_queue','dock_approach'));
        ALTER TABLE dock DROP CONSTRAINT IF EXISTS ck_dock_positive_size;
        ALTER TABLE slot DROP CONSTRAINT IF EXISTS ck_slot_positive_size;
        ALTER TABLE zone DROP CONSTRAINT IF EXISTS ck_zone_positive_size;
        ALTER TABLE plant DROP CONSTRAINT IF EXISTS ck_plant_segment;
        ALTER TABLE plant DROP COLUMN IF EXISTS active;
        ALTER TABLE plant DROP COLUMN IF EXISTS description;
        ALTER TABLE plant DROP COLUMN IF EXISTS city;
        ALTER TABLE plant DROP COLUMN IF EXISTS segment;
        DROP TABLE IF EXISTS auth_audit;
        DROP FUNCTION IF EXISTS yard_auth_audit_immutable();
        DROP TABLE IF EXISTS app_user;
        DROP FUNCTION IF EXISTS yard_user_protect_master()
        """
    )
