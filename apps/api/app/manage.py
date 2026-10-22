"""Comandos de operação.

    python -m app.manage service-user   # garante YARD_SIM_EMAIL como usuário de serviço

Usuário de serviço (simulador, integração) não passa pela tela: não tem quem troque a
senha no primeiro acesso, e o perfil é só o que a integração precisa.
"""

import asyncio
import os
import sys

from sqlalchemy import func, select

import app.models  # noqa: F401  (registra o metadata completo)
from app.core.db import SessionLocal
from app.modules.auth.models import AppUser
from app.modules.auth.passwords import hash_password, password_problem
from app.modules.auth.service import audit


async def service_user() -> str:
    email = os.environ.get("YARD_SIM_EMAIL", "").strip().lower()
    password = os.environ.get("YARD_SIM_PASSWORD", "")
    roles = sorted(os.environ.get("YARD_SIM_ROLES", "yard.gate").split(","))
    if not email or not password:
        return "YARD_SIM_EMAIL/YARD_SIM_PASSWORD ausentes: nada a fazer"
    if password_problem(password):
        raise SystemExit("YARD_SIM_PASSWORD fraca")
    async with SessionLocal() as session:
        user = (
            await session.execute(select(AppUser).where(func.lower(AppUser.email) == email))
        ).scalar_one_or_none()
        if user is None:
            session.add(
                AppUser(
                    email=email,
                    name="Simulador de campo",
                    roles=roles,
                    password_hash=hash_password(password),
                    must_change_password=False,
                    created_by="system",
                )
            )
            await audit(session, "user_created", actor="system", target_email=email, roles=roles)
            result = f"usuário de serviço criado: {email}"
        else:
            # a senha do .env é a fonte de verdade para conta de serviço
            user.password_hash = hash_password(password)
            user.roles = roles
            user.active = True
            user.must_change_password = False
            result = f"usuário de serviço atualizado: {email}"
        await session.commit()
    return result


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "service-user":
        print(asyncio.run(service_user()))
    else:
        raise SystemExit("uso: python -m app.manage service-user")


if __name__ == "__main__":
    main()
