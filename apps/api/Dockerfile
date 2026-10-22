FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Só dependências de execução: pytest/ruff (`.[dev]`) não entram na imagem de produção.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin yard

COPY alembic.ini ./
COPY alembic ./alembic

# Não-root (auditoria 2026-10): falha na API não vira root no contêiner.
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
