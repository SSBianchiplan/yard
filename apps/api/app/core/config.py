from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="YARD_", extra="ignore")

    database_url: str = "postgresql+asyncpg://yard:yard@localhost:5442/yard"
    # ASSUNÇÃO: uma planta por instância na Fatia 1; multi-planta entra como tenant na Fatia 8.
    plant_code: str = "PLANT-01"
    plant_timezone: str = "America/Sao_Paulo"
    cors_origins: str = "http://localhost:5173"
    env: str = "dev"  # dev | staging | prod

    # ---- autenticação -------------------------------------------------------
    # `open` só existe fora de produção; em prod o boot falha se ficar aberto.
    # `local`: usuários e senhas no próprio Postgres, token assinado pela API — para
    # instalação sem Keycloak (demonstração, planta pequena).
    auth_mode: str = "open"  # open | local | oidc
    auth_secret: str = "dev-inseguro-troque-em-producao"
    auth_token_hours: int = 12
    auth_max_failed_logins: int = 5
    auth_lock_minutes: int = 15
    # Admin master: criado no boot se ainda não existir. A senha só é lida na criação;
    # depois disso quem manda é o banco (e a tela de troca de senha).
    master_email: str | None = None
    master_password: str | None = None
    master_name: str = "Administrador master"
    oidc_issuer: str = "http://localhost:8080/realms/yard"
    oidc_jwks_url: str = "http://localhost:8080/realms/yard/protocol/openid-connect/certs"
    oidc_audience: str = "yard-api"

    # ---- campo (OT) ---------------------------------------------------------
    # Em produção, nada de simulador: o pátio fala com CLP, balança e câmera de verdade.
    field_mode: str = "simulator"  # simulator | live
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_group_id: str = "GPLANSIS"
    mqtt_node_id: str = "YARD-EDGE-01"
    mqtt_tls: bool = True
    opcua_endpoint: str | None = None
    opcua_username: str | None = None
    opcua_password: str | None = None

    # ---- operação -----------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False
    request_timeout_seconds: int = 30

    @model_validator(mode="after")
    def validate_local_auth(self) -> "Settings":
        """Token assinado com segredo fraco é autenticação de enfeite — vale fora de prod."""
        if self.auth_mode == "local" and (
            len(self.auth_secret) < 32 or self.auth_secret.startswith("dev-inseguro")
        ):
            raise ValueError("YARD_AUTH_SECRET precisa de ao menos 32 caracteres aleatórios")
        return self

    @property
    def is_production(self) -> bool:
        return self.env.lower() in ("prod", "production")

    @property
    def simulators_enabled(self) -> bool:
        """Rota de simulação só existe fora de produção — em prod ela nem é registrada."""
        return not self.is_production and self.field_mode == "simulator"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        """Produção tem exigências que não se negocia em tempo de execução.

        Falhar no boot é chato; subir em produção com autenticação aberta e simulador
        ligado é muito pior — e é o tipo de coisa que ninguém percebe até o dia ruim.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.auth_mode not in ("oidc", "local"):
            problems.append("YARD_AUTH_MODE deve ser 'oidc' ou 'local' em produção")
        if self.field_mode != "live":
            problems.append("YARD_FIELD_MODE deve ser 'live' em produção")
        if self.field_mode == "live" and not (self.mqtt_host or self.opcua_endpoint):
            problems.append("defina YARD_MQTT_HOST e/ou YARD_OPCUA_ENDPOINT para o campo")
        if self.auth_mode == "oidc" and "localhost" in self.oidc_issuer:
            problems.append("YARD_OIDC_ISSUER aponta para localhost")
        if any(origin in ("*", "http://localhost:5173") for origin in self.cors_list):
            problems.append("YARD_CORS_ORIGINS não pode ser '*' nem localhost em produção")
        if "yard:yard@" in self.database_url:
            problems.append("credencial padrão do banco em produção")

        if problems:
            raise ValueError(
                "configuração inválida para produção:\n  - " + "\n  - ".join(problems)
            )
        return self


settings = Settings()
