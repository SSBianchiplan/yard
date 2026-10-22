#!/usr/bin/env bash
# Roda NO SERVIDOR (chamado pelo enviar.sh). Idempotente: pode rodar a cada deploy.
# Pré-requisito: /opt/yard/.env existe (ver README — é criado uma vez, com segredos
# gerados no próprio servidor).
set -euo pipefail

APP=/opt/yard
[ -f "$APP/.env" ] || { echo "falta $APP/.env — veja deploy/vps/README.md"; exit 1; }
set -a; . "$APP/.env"; set +a

# Roda um comando como `yard` com o .env carregado (o sudo daqui não preserva ambiente).
as_yard() {
  runuser -u yard -- bash -c 'set -a; . /opt/yard/.env; set +a; cd /opt/yard/api; exec "$@"' _ "$@"
}

# 1. usuário de sistema, sem shell
id yard >/dev/null 2>&1 || useradd --system --home /var/lib/yard --shell /usr/sbin/nologin yard
install -d -o yard -g yard -m 750 /var/lib/yard
chown yard:yard "$APP/.env"; chmod 600 "$APP/.env"
# Código é do root e só ele escreve (o rsync antigo deixava uid 501 e modo 777: qualquer
# conta da máquina podia trocar o app que roda como `yard`).
chown -R root:root "$APP/api" "$APP/web" "$APP/deploy"
chmod -R u+rwX,go+rX,go-w "$APP/api" "$APP/web" "$APP/deploy"

# 2. banco: papel e base próprios; extensões criadas pelo superusuário
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${YARD_DB_USER}') THEN
    CREATE ROLE ${YARD_DB_USER} LOGIN PASSWORD '${YARD_DB_PASSWORD}';
  END IF;
END \$\$;
SQL
sudo -u postgres psql -Atc "SELECT 1 FROM pg_database WHERE datname='${YARD_DB_NAME}'" | grep -q 1 \
  || sudo -u postgres createdb -O "${YARD_DB_USER}" "${YARD_DB_NAME}"
sudo -u postgres psql -d "${YARD_DB_NAME}" -v ON_ERROR_STOP=1 -q <<SQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS vector;
SQL

# 3. dependências Python (venv próprio, versão do sistema)
[ -x "$APP/.venv/bin/python" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -e "$APP/api"
# python-jose (sem manutenção) e ecdsa (CVE-2024-23342) saíram: o token agora é PyJWT
"$APP/.venv/bin/pip" uninstall -q -y python-jose ecdsa 2>/dev/null || true
"$APP/.venv/bin/pip" install -q --upgrade 'certifi>=2026.10.19'

# 4. migrations (o ExecStartPre também roda; aqui falha cedo e visível)
as_yard "$APP/.venv/bin/python" -m alembic upgrade head

# 5. serviços
install -m 644 "$APP/deploy/yard.service" /etc/systemd/system/yard.service
install -m 644 "$APP/deploy/yard-sim.service" /etc/systemd/system/yard-sim.service
systemctl daemon-reload
systemctl enable -q yard yard-sim
systemctl restart yard
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:${YARD_PORT}/ready" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${YARD_PORT}/ready"; echo

# A senha inicial do master só serve para criá-lo; criado, ela sai do disco.
if grep -q '^YARD_MASTER_PASSWORD=' "$APP/.env" && \
   sudo -u postgres psql -d "${YARD_DB_NAME}" -Atc "SELECT 1 FROM app_user WHERE is_master" | grep -q 1; then
  sed -i '/^YARD_MASTER_PASSWORD=/d' "$APP/.env"
  echo "senha inicial do master removida do .env"
fi

# Simulador: conta de serviço garantida antes de subir
if [ -n "${YARD_SIM_EMAIL:-}" ]; then
  as_yard "$APP/.venv/bin/python" -m app.manage service-user
  systemctl restart yard-sim
fi

# 6. Caddy: bloco próprio, validado antes do reload
if ! cmp -s "$APP/deploy/yard.caddy" /etc/caddy/yard.caddy; then
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak-yard-$(date +%Y%m%d-%H%M%S)"
  install -m 644 "$APP/deploy/yard.caddy" /etc/caddy/yard.caddy
  grep -q "import /etc/caddy/yard.caddy" /etc/caddy/Caddyfile \
    || printf '\n# GPlanSiS|YARD\nimport /etc/caddy/yard.caddy\n' >> /etc/caddy/Caddyfile
  touch /var/log/caddy/yard.log; chown caddy:caddy /var/log/caddy/yard.log
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  systemctl reload caddy
fi
echo "yard instalado"
