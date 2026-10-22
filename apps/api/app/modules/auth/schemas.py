from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

KNOWN_ROLES = (
    "yard.scheduler",
    "yard.gate",
    "yard.scale",
    "yard.spotter",
    "yard.dock",
    "yard.supervisor",
    "yard.controller",
    "yard.admin",
    "yard.device",
)


def _email(value: str) -> str:
    value = value.strip().lower()
    local, _, domain = value.partition("@")
    if not local or "." not in domain or " " in value:
        raise ValueError("email")
    return value


def _roles(value: list[str]) -> list[str]:
    unknown = [role for role in value if role not in KNOWN_ROLES]
    if unknown:
        raise ValueError("roles")
    # ordem estável e sem repetição: diff de auditoria legível
    return sorted(set(value))


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)

    _norm = field_validator("email")(_email)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    roles: list[str]
    active: bool
    is_master: bool
    must_change_password: bool
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class SessionOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class UserCreateIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=2, max_length=160)
    roles: list[str] = Field(default_factory=list)
    # Sem senha: o sistema gera uma provisória, mostrada uma única vez.
    password: str | None = Field(default=None, max_length=200)

    _norm = field_validator("email")(_email)
    _r = field_validator("roles")(_roles)


class UserUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    roles: list[str] | None = None
    active: bool | None = None

    @field_validator("roles")
    @classmethod
    def _r(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _roles(value)


class UserWithPasswordOut(BaseModel):
    user: UserOut
    temporary_password: str | None = None


class AuthAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    event_type: str
    actor: str | None
    target_email: str | None
    ip: str | None
    payload: dict
