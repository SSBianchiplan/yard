"""Senha e token do modo `local`.

scrypt da biblioteca padrão: memória-dura, sem dependência nativa nova para compilar no
servidor. O hash carrega os próprios parâmetros, então subir o custo depois não
invalida as senhas antigas — elas só são regravadas no próximo login.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import settings
from app.core.errors import ERR_UNAUTHENTICATED, Unauthenticated

_N, _R, _P = 2**14, 8, 1
_ISSUER = "gplansis-yard"
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    salt_b64, digest_b64 = base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    return f"scrypt${_N}${_R}${_P}${salt_b64}${digest_b64}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = base64.b64decode(digest_b64)
    digest = hashlib.scrypt(
        password.encode(),
        salt=base64.b64decode(salt_b64),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(expected),
    )
    return hmac.compare_digest(digest, expected)


def password_problem(password: str) -> str | None:
    """Regra mínima e explicável: comprimento, letra e número. Devolve o código do problema."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "too_short"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "needs_letter_and_digit"
    return None


def temporary_password() -> str:
    """Senha provisória legível ao telefone: sem 0/O/1/l, com dígito garantido."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    digits = "23456789"
    body = "".join(secrets.choice(alphabet + digits) for _ in range(10))
    return body + secrets.choice(digits) + secrets.choice(digits)


def issue_token(subject: str, user_id: str) -> tuple[str, datetime]:
    expires = datetime.now(UTC) + timedelta(hours=settings.auth_token_hours)
    token = jwt.encode(
        {"sub": subject, "uid": user_id, "iss": _ISSUER, "exp": expires},
        settings.auth_secret,
        algorithm="HS256",
    )
    return token, expires


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.auth_secret,
            algorithms=["HS256"],
            issuer=_ISSUER,
            options={"require": ["exp", "iss", "uid"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated(ERR_UNAUTHENTICATED, reason="invalid_token") from exc
