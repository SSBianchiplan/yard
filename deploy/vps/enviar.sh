#!/usr/bin/env bash
# Deploy do YARD no servidor (yard.gplansis.com). Roda na sua máquina, da raiz ou de onde for.
#   bash deploy/vps/enviar.sh
set -euo pipefail
HOST=${YARD_HOST:?defina YARD_HOST=<servidor ssh>}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

echo "» build do front (gate de i18n + tsc + vite)"
( cd "$ROOT" && npm run build >/dev/null )

echo "» enviando código para $HOST:/opt/yard"
ssh "$HOST" 'install -d /opt/yard/api /opt/yard/web /opt/yard/deploy'
rsync -az --delete \
  --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
  --exclude '*.egg-info' --exclude .env --exclude tests \
  "$ROOT/apps/api/" "$HOST:/opt/yard/api/"
rsync -az --delete "$ROOT/apps/web/dist/" "$HOST:/opt/yard/web/"
rsync -az --delete "$ROOT/deploy/vps/" "$HOST:/opt/yard/deploy/"

echo "» instalando no servidor"
ssh "$HOST" 'bash /opt/yard/deploy/instalar-remoto.sh'
