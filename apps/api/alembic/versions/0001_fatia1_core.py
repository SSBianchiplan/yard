"""Fatia 1 — núcleo de pátio: cadastro, mapa, visita, ocupação e trilha.

Revision ID: 0001_fatia1_core
Create Date: 2026-09-20

Invariantes que ficam no banco, de propósito:
  - veículo não ocupa duas vagas ao mesmo tempo      (EXCLUDE em slot_occupancy)
  - vaga não recebe duas ocupações sobrepostas       (EXCLUDE em slot_occupancy)
  - um veículo tem no máximo uma visita aberta       (índice único parcial)
  - trilha de auditoria é append-only                (trigger)
  - saída não ocorre com pendência aberta            (CHECK em visit)
"""

from alembic import op

revision = "0001_fatia1_core"
down_revision = None
branch_labels = None
depends_on = None


def _split(script: str) -> list[str]:
    """Divide o script em comandos, preservando blocos $$ ... $$ de plpgsql.

    asyncpg não aceita múltiplos comandos num mesmo statement preparado, então a migration
    executa comando a comando — o SQL abaixo segue legível como um bloco só.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_dollar = False
    index = 0
    while index < len(script):
        if script.startswith("$$", index):
            in_dollar = not in_dollar
            buffer.append("$$")
            index += 2
            continue
        char = script[index]
        if char == ";" and not in_dollar:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _exec(script: str) -> None:
    for statement in _split(script):
        op.execute(statement)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # TimescaleDB e pgvector são opcionais no dev local; obrigatórios em produção.
    _exec(
        """
        DO $$ BEGIN
            CREATE EXTENSION IF NOT EXISTS timescaledb;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'timescaledb indisponível: visit_event fica tabela comum';
        END $$;
        """
    )
    _exec(
        """
        DO $$ BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pgvector indisponível';
        END $$;
        """
    )

    _exec(
        """
        CREATE TABLE plant (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(32) NOT NULL UNIQUE,
            name varchar(120) NOT NULL,
            timezone varchar(64) NOT NULL DEFAULT 'America/Sao_Paulo',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE carrier (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(32) NOT NULL UNIQUE,
            name varchar(160) NOT NULL,
            tax_id varchar(32),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE driver (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            full_name varchar(160) NOT NULL,
            document varchar(32) NOT NULL UNIQUE,
            license_number varchar(32),
            license_expires_on date,
            phone varchar(32),
            carrier_id uuid REFERENCES carrier(id),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE vehicle (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plate varchar(16) NOT NULL UNIQUE,
            trailer_plate varchar(16),
            kind varchar(32) NOT NULL,
            carrier_id uuid REFERENCES carrier(id),
            axles integer,
            tare_kg integer,
            max_gross_kg integer,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_vehicle_kind CHECK (kind IN
                ('truck','truck_trailer','van','container_chassis','tanker')),
            CONSTRAINT ck_vehicle_tare CHECK (tare_kg IS NULL OR tare_kg > 0),
            CONSTRAINT ck_vehicle_gross CHECK (
                max_gross_kg IS NULL OR tare_kg IS NULL OR max_gross_kg >= tare_kg)
        );

        CREATE TABLE product (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            sku varchar(48) NOT NULL UNIQUE,
            name varchar(160) NOT NULL,
            hazardous boolean NOT NULL DEFAULT false,
            unit varchar(8) NOT NULL DEFAULT 'kg',
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE operation_type (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(32) NOT NULL UNIQUE,
            direction varchar(16) NOT NULL,
            requires_weighing boolean NOT NULL DEFAULT false,
            requires_dock boolean NOT NULL DEFAULT true,
            target_dwell_minutes integer NOT NULL DEFAULT 90,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_operation_type_direction CHECK
                (direction IN ('inbound','outbound','transit')),
            CONSTRAINT ck_operation_type_dwell CHECK (target_dwell_minutes > 0)
        );
        """
    )

    _exec(
        """
        CREATE TABLE zone (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(32) NOT NULL UNIQUE,
            kind varchar(32) NOT NULL DEFAULT 'parking',
            x numeric(10,2) NOT NULL DEFAULT 0,
            y numeric(10,2) NOT NULL DEFAULT 0,
            width numeric(10,2) NOT NULL DEFAULT 100,
            height numeric(10,2) NOT NULL DEFAULT 100,
            color_token varchar(48),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE gate (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(32) NOT NULL UNIQUE,
            direction varchar(16) NOT NULL DEFAULT 'both',
            x numeric(10,2) NOT NULL DEFAULT 0,
            y numeric(10,2) NOT NULL DEFAULT 0,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_gate_direction CHECK (direction IN ('in','out','both'))
        );

        CREATE TABLE scale (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            code varchar(32) NOT NULL UNIQUE,
            capacity_kg integer NOT NULL DEFAULT 80000,
            x numeric(10,2) NOT NULL DEFAULT 0,
            y numeric(10,2) NOT NULL DEFAULT 0,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE dock (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            zone_id uuid REFERENCES zone(id),
            code varchar(32) NOT NULL UNIQUE,
            direction varchar(16) NOT NULL DEFAULT 'inbound',
            status varchar(16) NOT NULL DEFAULT 'available',
            x numeric(10,2) NOT NULL DEFAULT 0,
            y numeric(10,2) NOT NULL DEFAULT 0,
            width numeric(10,2) NOT NULL DEFAULT 8,
            height numeric(10,2) NOT NULL DEFAULT 14,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_dock_status CHECK (status IN ('available','occupied','blocked'))
        );

        CREATE TABLE slot (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            zone_id uuid NOT NULL REFERENCES zone(id),
            code varchar(32) NOT NULL UNIQUE,
            kind varchar(32) NOT NULL DEFAULT 'parking',
            status varchar(16) NOT NULL DEFAULT 'available',
            length_m numeric(6,2) NOT NULL DEFAULT 18,
            x numeric(10,2) NOT NULL DEFAULT 0,
            y numeric(10,2) NOT NULL DEFAULT 0,
            width numeric(10,2) NOT NULL DEFAULT 4,
            height numeric(10,2) NOT NULL DEFAULT 12,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_slot_status CHECK (status IN ('available','blocked','maintenance')),
            CONSTRAINT ck_slot_kind CHECK (kind IN
                ('parking','staging','quarantine','scale_queue','dock_approach'))
        );
        CREATE INDEX ix_slot_zone_id ON slot(zone_id);
        """
    )

    _exec(
        """
        CREATE SEQUENCE visit_reference_seq;

        CREATE TABLE visit (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id uuid NOT NULL REFERENCES plant(id),
            reference varchar(24) NOT NULL UNIQUE,
            state varchar(24) NOT NULL DEFAULT 'at_gate_in',
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            driver_id uuid NOT NULL REFERENCES driver(id),
            carrier_id uuid REFERENCES carrier(id),
            product_id uuid REFERENCES product(id),
            operation_type_id uuid NOT NULL REFERENCES operation_type(id),
            gate_in_id uuid REFERENCES gate(id),
            gate_out_id uuid REFERENCES gate(id),
            current_slot_id uuid REFERENCES slot(id),
            current_dock_id uuid REFERENCES dock(id),
            arrived_at timestamptz NOT NULL,
            gate_in_at timestamptz,
            dock_in_at timestamptz,
            dock_out_at timestamptz,
            gate_out_at timestamptz,
            seal_number varchar(48),
            document_number varchar(64),
            notes text,
            blocked_reason_code varchar(48),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_visit_state CHECK (state IN
                ('expected','at_gate_in','in_yard','at_dock','at_gate_out','departed','rejected')),
            CONSTRAINT ck_visit_timeline CHECK (
                (gate_in_at IS NULL OR gate_in_at >= arrived_at)
                AND (gate_out_at IS NULL OR gate_in_at IS NULL OR gate_out_at >= gate_in_at)
                AND (dock_out_at IS NULL OR dock_in_at IS NULL OR dock_out_at >= dock_in_at)
            ),
            -- saída não ocorre com pendência fiscal/operacional aberta
            CONSTRAINT ck_visit_exit_not_blocked CHECK (
                state <> 'departed' OR blocked_reason_code IS NULL
            ),
            CONSTRAINT ck_visit_departed_has_timestamp CHECK (
                state <> 'departed' OR gate_out_at IS NOT NULL
            )
        );

        -- um veículo tem no máximo uma visita aberta por vez
        CREATE UNIQUE INDEX uq_visit_open_vehicle ON visit(vehicle_id)
            WHERE state IN ('at_gate_in','in_yard','at_dock','at_gate_out');
        CREATE INDEX ix_visit_state ON visit(state);
        CREATE INDEX ix_visit_arrived_at ON visit(arrived_at DESC);
        """
    )

    _exec(
        """
        CREATE TABLE slot_occupancy (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slot_id uuid NOT NULL REFERENCES slot(id),
            visit_id uuid NOT NULL REFERENCES visit(id),
            vehicle_id uuid NOT NULL REFERENCES vehicle(id),
            started_at timestamptz NOT NULL,
            ended_at timestamptz,
            period tstzrange GENERATED ALWAYS AS (tstzrange(started_at, ended_at)) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_slot_occupancy_period CHECK (ended_at IS NULL OR ended_at > started_at),
            CONSTRAINT ex_slot_occupancy_slot EXCLUDE USING gist (
                slot_id WITH =, period WITH &&),
            CONSTRAINT ex_slot_occupancy_vehicle EXCLUDE USING gist (
                vehicle_id WITH =, period WITH &&)
        );
        CREATE INDEX ix_slot_occupancy_visit_id ON slot_occupancy(visit_id);
        """
    )

    _exec(
        """
        CREATE TABLE visit_event (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            visit_id uuid NOT NULL REFERENCES visit(id),
            event_type varchar(32) NOT NULL,
            source varchar(24) NOT NULL DEFAULT 'manual',
            actor varchar(120),
            from_state varchar(24),
            to_state varchar(24),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT ck_visit_event_source CHECK (source IN
                ('manual','device','simulator','system','ai_confirmed'))
        );
        CREATE INDEX ix_visit_event_visit_id ON visit_event(visit_id, occurred_at DESC);

        DO $$ BEGIN
            PERFORM create_hypertable('visit_event','occurred_at',
                     chunk_time_interval => interval '7 days', migrate_data => true);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'visit_event permanece tabela comum';
        END $$;
        """
    )

    # Auditoria append-only: quem quiser corrigir um evento, emite outro evento.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_deny_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ERR_YARD_AUDIT_IMMUTABLE'
                USING ERRCODE = 'check_violation';
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_visit_event_append_only
            BEFORE UPDATE OR DELETE ON visit_event
            FOR EACH ROW EXECUTE FUNCTION yard_deny_mutation();
        """
    )

    # Vaga bloqueada/manutenção não recebe ocupação nova.
    _exec(
        """
        CREATE OR REPLACE FUNCTION yard_check_slot_available() RETURNS trigger AS $$
        DECLARE s varchar(16);
        BEGIN
            SELECT status INTO s FROM slot WHERE id = NEW.slot_id;
            IF s <> 'available' THEN
                RAISE EXCEPTION 'ERR_YARD_SLOT_BLOCKED' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_slot_occupancy_slot_available
            BEFORE INSERT ON slot_occupancy
            FOR EACH ROW EXECUTE FUNCTION yard_check_slot_available();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS visit_event CASCADE")
    op.execute("DROP TABLE IF EXISTS slot_occupancy CASCADE")
    op.execute("DROP TABLE IF EXISTS visit CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS visit_reference_seq")
    op.execute("DROP TABLE IF EXISTS slot CASCADE")
    op.execute("DROP TABLE IF EXISTS dock CASCADE")
    op.execute("DROP TABLE IF EXISTS scale CASCADE")
    op.execute("DROP TABLE IF EXISTS gate CASCADE")
    op.execute("DROP TABLE IF EXISTS zone CASCADE")
    op.execute("DROP TABLE IF EXISTS operation_type CASCADE")
    op.execute("DROP TABLE IF EXISTS product CASCADE")
    op.execute("DROP TABLE IF EXISTS vehicle CASCADE")
    op.execute("DROP TABLE IF EXISTS driver CASCADE")
    op.execute("DROP TABLE IF EXISTS carrier CASCADE")
    op.execute("DROP TABLE IF EXISTS plant CASCADE")
    op.execute("DROP FUNCTION IF EXISTS yard_check_slot_available")
    op.execute("DROP FUNCTION IF EXISTS yard_deny_mutation")
