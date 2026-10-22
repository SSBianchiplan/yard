from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class AppUser(PkMixin, TimestampMixin, Base):
    """Usuário local (`YARD_AUTH_MODE=local`). Invariantes do master vivem na migration 0013."""

    __tablename__ = "app_user"

    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    active: Mapped[bool] = mapped_column(default=True)
    is_master: Mapped[bool] = mapped_column(default=False)
    must_change_password: Mapped[bool] = mapped_column(default=True)
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
    created_by: Mapped[str | None] = mapped_column(String(254))


class AuthAudit(Base):
    """Trilha de acesso, append-only (trigger na migration 0013)."""

    __tablename__ = "auth_audit"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    event_type: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(254))
    target_email: Mapped[str | None] = mapped_column(String(254))
    ip: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
