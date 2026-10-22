"""Fatia 8 — integrações: outbox transacional, fiscal brasileiro e notificação.

Revision ID: 0008_fatia8_integrations
Create Date: 2026-09-20

Invariantes que ficam no banco:
  - a mensagem do outbox é única por (agregado, sequência)   (índice único)
  - chave idempotente não processa duas vezes                (índice único)
  - chave de NF-e/CT-e/MDF-e tem 44 dígitos                  (CHECK)
  - opt-out respeitado: não se envia para quem recusou       (CHECK)
  - mensagem estourou o retry → dead-letter, nunca sumiu     (CHECK)
"""

from app.core.migration_sql import exec_script as _exec

revision = "0008_fatia8_integrations"
down_revision = "0007_fatia7_control_tower"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE integration_endpoint (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(48) NOT NULL UNIQUE,
            system varchar(32) NOT NULL,
            direction varchar(8) NOT NULL DEFAULT 'out',
            url varchar(300),
            auth_kind varchar(24) NOT NULL DEFAULT 'none',
            active boolean NOT NULL DEFAULT true,
            max_retry integer NOT NULL DEFAULT 8,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_endpoint_system CHECK (system IN
                ('sap_b1','sap_hana','odoo','opcenter','wms','tms','pcp','bi','webhook',
                 'notification')),
            CONSTRAINT ck_endpoint_direction CHECK (direction IN ('in','out','both')),
            CONSTRAINT ck_endpoint_auth CHECK (auth_kind IN
                ('none','basic','bearer','hmac','oauth2')),
            CONSTRAINT ck_endpoint_retry CHECK (max_retry BETWEEN 0 AND 50)
        );

        CREATE TABLE outbox_message (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            endpoint_id uuid REFERENCES integration_endpoint(id),
            aggregate_type varchar(32) NOT NULL,
            aggregate_id uuid NOT NULL,
            event_seq bigint NOT NULL,
            event_type varchar(48) NOT NULL,
            payload jsonb NOT NULL,
            state varchar(16) NOT NULL DEFAULT 'pending',
            retry_count integer NOT NULL DEFAULT 0,
            max_retry integer NOT NULL DEFAULT 8,
            next_attempt_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            acknowledged_at timestamptz,
            last_error varchar(300),
            CONSTRAINT ck_outbox_state CHECK (state IN
                ('pending','sent','acknowledged','failed','dead_letter')),
            -- mensagem que estourou o retry vira dead-letter visível, não desaparece
            CONSTRAINT ck_outbox_retry CHECK (
                retry_count <= max_retry OR state = 'dead_letter'),
            CONSTRAINT ck_outbox_sent CHECK (state <> 'sent' OR sent_at IS NOT NULL)
        );
        -- o mesmo fato de negócio publica uma vez só
        CREATE UNIQUE INDEX uq_outbox_dedup
            ON outbox_message(aggregate_type, aggregate_id, event_seq, event_type);
        CREATE INDEX ix_outbox_pending ON outbox_message(state, next_attempt_at)
            WHERE state IN ('pending','failed');

        CREATE TABLE inbox_message (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            received_at timestamptz NOT NULL DEFAULT now(),
            endpoint_id uuid REFERENCES integration_endpoint(id),
            external_id varchar(120) NOT NULL,
            event_type varchar(48) NOT NULL,
            payload jsonb NOT NULL,
            state varchar(16) NOT NULL DEFAULT 'received',
            processed_at timestamptz,
            error varchar(300),
            CONSTRAINT ck_inbox_state CHECK (state IN
                ('received','processed','rejected','duplicate')),
            CONSTRAINT uq_inbox_external UNIQUE (endpoint_id, external_id)
        );

        CREATE TABLE api_request (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            client_id varchar(64) NOT NULL,
            idempotency_key varchar(120) NOT NULL,
            method varchar(8) NOT NULL,
            path varchar(240) NOT NULL,
            status_code integer,
            response_json jsonb,
            CONSTRAINT uq_idempotency_key UNIQUE (client_id, idempotency_key)
        );
        """
    )

    _exec(
        """
        CREATE TABLE fiscal_document (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            visit_id uuid REFERENCES visit(id),
            kind varchar(16) NOT NULL,
            access_key varchar(44),
            number varchar(32),
            series varchar(8),
            issuer_tax_id varchar(32),
            net_weight_kg integer,
            state varchar(16) NOT NULL DEFAULT 'received',
            validated_at timestamptz,
            rejection_code varchar(48),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- NF-e, CT-e, MDF-e e romaneio são termo próprio brasileiro: não se traduzem
            CONSTRAINT ck_fiscal_kind CHECK (kind IN
                ('nfe','cte','mdfe','packing_list','collection_order')),
            CONSTRAINT ck_fiscal_state CHECK (state IN
                ('received','validated','rejected','cancelled')),
            -- chave de acesso tem 44 dígitos; qualquer outra coisa é erro de digitação
            CONSTRAINT ck_fiscal_key CHECK (
                kind NOT IN ('nfe','cte','mdfe')
                OR (access_key IS NOT NULL AND access_key ~ '^[0-9]{44}$')),
            CONSTRAINT ck_fiscal_validated CHECK (
                state <> 'validated' OR validated_at IS NOT NULL),
            CONSTRAINT ck_fiscal_rejected CHECK (
                state <> 'rejected' OR rejection_code IS NOT NULL)
        );
        CREATE UNIQUE INDEX uq_fiscal_access_key ON fiscal_document(access_key)
            WHERE access_key IS NOT NULL;
        CREATE INDEX ix_fiscal_visit ON fiscal_document(visit_id);

        CREATE TABLE notification_optout (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            channel varchar(16) NOT NULL,
            address varchar(160) NOT NULL,
            opted_out_at timestamptz NOT NULL DEFAULT now(),
            reason_code varchar(48),
            CONSTRAINT uq_optout UNIQUE (channel, address)
        );

        CREATE TABLE notification (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            visit_id uuid REFERENCES visit(id),
            appointment_id uuid REFERENCES appointment(id),
            channel varchar(16) NOT NULL,
            address varchar(160) NOT NULL,
            template_code varchar(48) NOT NULL,
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            state varchar(16) NOT NULL DEFAULT 'queued',
            opted_out boolean NOT NULL DEFAULT false,
            sent_at timestamptz,
            delivered_at timestamptz,
            read_at timestamptz,
            failure_code varchar(48),
            provider_message_id varchar(120),
            CONSTRAINT ck_notification_channel CHECK (channel IN
                ('whatsapp','sms','email','app','voice')),
            CONSTRAINT ck_notification_state CHECK (state IN
                ('queued','sent','delivered','read','failed','opted_out')),
            -- opt-out é respeitado em qualquer canal, inclusive no automático
            CONSTRAINT ck_notification_optout CHECK (
                state NOT IN ('sent','delivered','read') OR opted_out = false),
            CONSTRAINT ck_notification_sent CHECK (state <> 'sent' OR sent_at IS NOT NULL)
        );
        CREATE INDEX ix_notification_visit ON notification(visit_id, created_at DESC);

        CREATE TABLE delivery_log (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            notification_id uuid NOT NULL REFERENCES notification(id),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            state varchar(16) NOT NULL,
            detail varchar(300)
        );
        CREATE INDEX ix_delivery_log_notification ON delivery_log(notification_id, occurred_at);
        """
    )

    # Opt-out é regra, não recomendação: o banco recusa enviar para quem saiu.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_notification_optout() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM notification_optout o
                 WHERE o.channel = NEW.channel AND o.address = NEW.address
            ) THEN
                NEW.opted_out := true;
                NEW.state := 'opted_out';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_notification_optout
            BEFORE INSERT ON notification
            FOR EACH ROW EXECUTE FUNCTION yard_notification_optout();
        """
    )

    # Outbox: gravar o fato e a mensagem na MESMA transação é o ponto do padrão.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_outbox_from_visit_event() RETURNS trigger AS $$
        BEGIN
            INSERT INTO outbox_message (
                aggregate_type, aggregate_id, event_seq, event_type, payload, state
            )
            VALUES (
                'visit',
                NEW.visit_id,
                (EXTRACT(EPOCH FROM NEW.occurred_at) * 1000)::bigint,
                'visit.' || NEW.event_type,
                jsonb_build_object(
                    'visit_id', NEW.visit_id,
                    'event_type', NEW.event_type,
                    'occurred_at', NEW.occurred_at,
                    'source', NEW.source,
                    'from_state', NEW.from_state,
                    'to_state', NEW.to_state,
                    'payload', NEW.payload
                ),
                'pending'
            )
            ON CONFLICT DO NOTHING;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_visit_event_outbox
            AFTER INSERT ON visit_event
            FOR EACH ROW EXECUTE FUNCTION yard_outbox_from_visit_event();
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP TRIGGER IF EXISTS trg_visit_event_outbox ON visit_event;
        DROP FUNCTION IF EXISTS yard_outbox_from_visit_event;
        DROP TABLE IF EXISTS delivery_log CASCADE;
        DROP TABLE IF EXISTS notification CASCADE;
        DROP TABLE IF EXISTS notification_optout CASCADE;
        DROP FUNCTION IF EXISTS yard_notification_optout;
        DROP TABLE IF EXISTS fiscal_document CASCADE;
        DROP TABLE IF EXISTS api_request CASCADE;
        DROP TABLE IF EXISTS inbox_message CASCADE;
        DROP TABLE IF EXISTS outbox_message CASCADE;
        DROP TABLE IF EXISTS integration_endpoint CASCADE;
        """
    )
