# Deploy — yard.gplansis.com

Mesmo desenho dos outros sistemas do hub: **venv + systemd + Caddy**, sem Docker.

| Peça | Onde |
|---|---|
| código da API | `/opt/yard/api` (somente leitura para o serviço) |
| SPA (build do Vite) | `/opt/yard/web`, servida direto pelo Caddy |
| segredos | `/opt/yard/.env` (600, dono `yard`) — **nunca** versionado |
| banco | Postgres 18 local, base `yard`, papel `yard_app` |
| API | `yard.service` → uvicorn em `127.0.0.1:8990`, 1 worker (barramento da torre é in-process) |
| simulador | `yard-sim.service` → chegadas pela API como `simulador@yard.gplansis.com` |
| TLS | Caddy, `/etc/caddy/yard.caddy`, certificado Let's Encrypt automático |

## Atualizar

```bash
bash deploy/vps/enviar.sh
```

Faz o build do front (com o gate de i18n), envia API/SPA/arquivos de deploy por rsync e
roda `instalar-remoto.sh` no servidor: dependências, migrations, units do systemd,
bloco do Caddy (validado antes do reload). É idempotente.

## Primeira instalação

1. DNS `yard.gplansis.com` → IP público do servidor.
2. Criar `/opt/yard/.env` **no servidor** (segredos gerados lá, com `openssl rand`):
   `YARD_ENV=prod`, `YARD_DEMO=true` (demonstração: campo pelo simulador, todas as
   outras travas de produção ligadas), `YARD_PORT=8990`, `YARD_DB_USER/NAME/PASSWORD`,
   `YARD_DATABASE_URL`, `YARD_CORS_ORIGINS=https://yard.gplansis.com`,
   `YARD_AUTH_MODE=local`, `YARD_AUTH_SECRET`, `YARD_MASTER_EMAIL`,
   `YARD_MASTER_NAME`, `YARD_MASTER_PASSWORD`, `YARD_SIM_EMAIL`, `YARD_SIM_PASSWORD`,
   `YARD_SIM_ROLES=yard.gate`, `YARD_SIM_RATE`, `YARD_FIELD_MODE=simulator`.
3. `bash deploy/vps/enviar.sh`. Depois que o master existe, o instalador **apaga**
   `YARD_MASTER_PASSWORD` do `.env`.
4. Seed da demonstração (uma vez só — ele trunca o pátio):
   ```bash
   ssh $HOST 'runuser -u yard -- bash -c "set -a; . /opt/yard/.env; set +a; cd /opt/yard/api;
     /opt/yard/.venv/bin/python -m app.seed && /opt/yard/.venv/bin/python -m app.seed_scheduling &&
     /opt/yard/.venv/bin/python -m app.seed_gate"'
   ```

## Operar

```bash
ssh $HOST 'journalctl -u yard -f'        # API
ssh $HOST 'journalctl -u yard-sim -f'    # simulador
ssh $HOST 'systemctl restart yard'       # nunca pkill uvicorn: há outros sistemas na máquina
```

## Portal do transportador

O portal (`/portal/v1/*`) não aceita mais só o código da transportadora. Cada uma recebe
uma chave própria, mostrada uma vez (gerar de novo revoga a anterior):

```bash
ssh $HOST 'runuser -u yard -- bash -c "set -a; . /opt/yard/.env; set +a; cd /opt/yard/api;
  /opt/yard/.venv/bin/python -m app.manage portal-key CODIGO_DA_TRANSPORTADORA"'
```

ou, pela API, `POST /api/v1/catalog/carriers/{id}/portal-key` (perfil `yard.admin`).
A transportadora chama o portal com `Authorization: Bearer ypk_…`. No modo `oidc` vale
também o token do Keycloak com o perfil `portal.carrier` e a claim `carrier_code`.

