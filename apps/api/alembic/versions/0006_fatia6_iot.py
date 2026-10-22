"""Fatia 6 — IoT/OT: modelo de informação único, telemetria, saúde e operação degradada.

Revision ID: 0006_fatia6_iot
Create Date: 2026-09-20

Invariantes que ficam no banco:
  - toda leitura carrega qualidade explícita              (CHECK)
  - evento de campo é idempotente por (device, tag, hora) (índice único)
  - lote do edge só entra uma vez                         (índice único)
  - permissivo de segurança é sinal, não opinião          (CHECK de tipo)
  - posição RTLS é camada opcional: nada depende dela     (FK anulável, sem trigger)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0006_fatia6_iot"
down_revision = "0005_fatia5_moves_docks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        -- Modelo de informação único: plant/area/line/device/signal.
        -- A aplicação nunca conhece endereço de tag do CLP; conhece este caminho.
        CREATE TABLE signal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id uuid NOT NULL REFERENCES device(id),
            code varchar(64) NOT NULL,
            path varchar(200) NOT NULL,
            kind varchar(24) NOT NULL,
            data_type varchar(16) NOT NULL DEFAULT 'bool',
            unit varchar(16),
            safety_related boolean NOT NULL DEFAULT false,
            stale_after_seconds integer NOT NULL DEFAULT 30,
            source_address varchar(160),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_signal_device_code UNIQUE (device_id, code),
            CONSTRAINT uq_signal_path UNIQUE (path),
            CONSTRAINT ck_signal_kind CHECK (kind IN
                ('permissive','status','measure','command_feedback','alarm','position')),
            CONSTRAINT ck_signal_data_type CHECK (data_type IN
                ('bool','int','float','string')),
            -- permissivo de segurança é booleano, sempre: "meio permissivo" não existe
            CONSTRAINT ck_signal_permissive_bool CHECK (
                kind <> 'permissive' OR data_type = 'bool'),
            CONSTRAINT ck_signal_stale CHECK (stale_after_seconds > 0)
        );

        CREATE TABLE signal_reading (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            signal_id uuid NOT NULL REFERENCES signal(id),
            device_id uuid NOT NULL REFERENCES device(id),
            value_bool boolean,
            value_num numeric(18,4),
            value_text varchar(240),
            quality varchar(16) NOT NULL DEFAULT 'good',
            sequence_number bigint,
            batch_id uuid,
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT ck_signal_reading_quality CHECK (quality IN
                ('good','stale','invalid','no_comm')),
            -- leitura sem valor nenhum é ruído, não dado
            CONSTRAINT ck_signal_reading_value CHECK (
                value_bool IS NOT NULL OR value_num IS NOT NULL OR value_text IS NOT NULL
                OR quality <> 'good')
        );
        CREATE UNIQUE INDEX uq_signal_reading_dedup
            ON signal_reading(signal_id, occurred_at, device_id);
        CREATE INDEX ix_signal_reading_signal ON signal_reading(signal_id, occurred_at DESC);

        DO $$ BEGIN
            PERFORM create_hypertable('signal_reading','occurred_at',
                     chunk_time_interval => interval '1 day', migrate_data => true);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'signal_reading permanece tabela comum';
        END $$;

        DO $$ BEGIN
            ALTER TABLE signal_reading SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'signal_id'
            );
            PERFORM add_compression_policy('signal_reading', interval '7 days');
            PERFORM add_retention_policy('signal_reading', interval '180 days');
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'políticas de compressão/retenção indisponíveis sem timescale';
        END $$;
        """
    )

    _exec(
        """
        CREATE TABLE device_health (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            device_id uuid NOT NULL REFERENCES device(id),
            status varchar(16) NOT NULL,
            latency_ms integer,
            error_code varchar(48),
            detail varchar(240),
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT ck_device_health_status CHECK (status IN
                ('online','degraded','offline','maintenance'))
        );
        CREATE INDEX ix_device_health_device ON device_health(device_id, occurred_at DESC);

        -- Operação degradada: o edge guarda o que aconteceu e reconcilia ao religar.
        CREATE TABLE edge_batch (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_key varchar(80) NOT NULL UNIQUE,
            edge_node varchar(64) NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            event_count integer NOT NULL DEFAULT 0,
            applied_count integer NOT NULL DEFAULT 0,
            skipped_count integer NOT NULL DEFAULT 0,
            oldest_event_at timestamptz,
            newest_event_at timestamptz,
            CONSTRAINT ck_edge_batch_counts CHECK (
                applied_count >= 0 AND skipped_count >= 0
                AND applied_count + skipped_count <= event_count)
        );

        -- RTLS é camada OPCIONAL de precisão. Nenhuma regra de negócio depende dela:
        -- o pátio funciona sem, e ganha precisão com.
        CREATE TABLE rtls_position (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            vehicle_id uuid REFERENCES vehicle(id),
            asset_tag varchar(64),
            technology varchar(16) NOT NULL,
            x numeric(10,2) NOT NULL,
            y numeric(10,2) NOT NULL,
            accuracy_m numeric(6,2),
            slot_id uuid REFERENCES slot(id),
            quality varchar(16) NOT NULL DEFAULT 'good',
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT ck_rtls_tech CHECK (technology IN ('gps','rtk','uwb','ble','rfid')),
            CONSTRAINT ck_rtls_quality CHECK (quality IN ('good','stale','invalid','no_comm')),
            CONSTRAINT ck_rtls_subject CHECK (vehicle_id IS NOT NULL OR asset_tag IS NOT NULL)
        );
        CREATE INDEX ix_rtls_vehicle ON rtls_position(vehicle_id, occurred_at DESC);

        DO $$ BEGIN
            PERFORM create_hypertable('rtls_position','occurred_at',
                     chunk_time_interval => interval '1 day', migrate_data => true);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'rtls_position permanece tabela comum';
        END $$;
        """
    )

    # Última leitura de cada sinal, com frescor calculado — é o que a torre lê.
    _exec(
        """
        CREATE OR REPLACE VIEW signal_current AS
        SELECT DISTINCT ON (r.signal_id)
               r.signal_id,
               s.code,
               s.path,
               s.kind,
               s.safety_related,
               d.code AS device_code,
               d.status AS device_status,
               r.occurred_at,
               r.received_at,
               r.value_bool,
               r.value_num,
               r.value_text,
               CASE
                   WHEN d.status IN ('offline','maintenance') THEN 'no_comm'
                   WHEN r.quality <> 'good' THEN r.quality
                   WHEN now() - r.occurred_at >
                        (s.stale_after_seconds || ' seconds')::interval THEN 'stale'
                   ELSE 'good'
               END AS quality
          FROM signal_reading r
          JOIN signal s ON s.id = r.signal_id
          JOIN device d ON d.id = s.device_id
         ORDER BY r.signal_id, r.occurred_at DESC;
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP VIEW IF EXISTS signal_current;
        DROP TABLE IF EXISTS rtls_position CASCADE;
        DROP TABLE IF EXISTS edge_batch CASCADE;
        DROP TABLE IF EXISTS device_health CASCADE;
        DROP TABLE IF EXISTS signal_reading CASCADE;
        DROP TABLE IF EXISTS signal CASCADE;
        """
    )
