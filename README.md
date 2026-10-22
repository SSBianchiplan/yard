<p align="center">
  <a href="https://yard.gplansis.com"><img src=".github/capa.png" alt="GPlanSiS|YARD — da guarita à doca, o pátio operando em tempo real" width="100%"></a>
</p>

<h1 align="center">GPlanSiS|YARD</h1>

<p align="center">
  <strong>Yard Operating System industrial: portaria, agendamento de docas, balança, manobra e torre de controle numa plataforma só.</strong><br>
  A camada que <em>orquestra</em> o que acontece entre a guarita e a doca — não apenas registra. A IA propõe; o humano decide.
</p>

<p align="center">
  <a href="https://yard.gplansis.com"><img alt="No ar" src="https://img.shields.io/badge/no%20ar-yard.gplansis.com-f28c28?style=flat-square"></a>
  <img alt="Versão" src="https://img.shields.io/badge/vers%C3%A3o-0.1.0-0b1b2b?style=flat-square">
  <a href="LICENSE"><img alt="licença MIT" src="https://img.shields.io/badge/licen%C3%A7a-MIT-2ea44f?style=flat-square"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12+-0b1b2b?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-PostgreSQL-0b1b2b?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React_19-Vite-0b1b2b?style=flat-square&logo=react&logoColor=white">
  <img alt="Testes" src="https://img.shields.io/badge/testes-96-2e7d32?style=flat-square">
  <a href="CONTRIBUTING.md"><img alt="Contribuições bem-vindas" src="https://img.shields.io/badge/contribui%C3%A7%C3%B5es-bem--vindas-2e7d32?style=flat-square"></a>
</p>

<p align="center">
  <a href="https://yard.gplansis.com"><b>➜ Abrir o GPlanSiS|YARD em yard.gplansis.com</b></a>
  &nbsp;·&nbsp; demonstração ao vivo com uma planta de alimentos fictícia e simulador de campo
</p>

---

## O que é

O **GPlanSiS|YARD** controla o ciclo do veículo na planta — **guarita → balança → vaga → doca → saída** — numa torre de controle viva: mapa do pátio, fila, ocupação, dwell e risco de demurrage em tempo real, com cada ação registrada numa trilha append-only.

O projeto segue três princípios que aparecem no código inteiro:

- **Invariante caro na aplicação é barato no banco.** Vaga, doca e janela de agendamento exclusivas são `EXCLUDE` no PostgreSQL; ticket de balança fechado é imutável; trilha de eventos é só acréscimo. Os testes tentam violar cada invariante por SQL cru.
- **A IA propõe, o humano decide.** Proposta do agente nasce em `proposed`; comando físico de origem IA exige `approved_by`, e um trigger recusa comando ligado a proposta não aprovada ou vencida.
- **Qualidade do dado é dado.** Sinal de campo carrega `good | stale | invalid | no_comm`; permissivo obsoleto **não** abre cancela.

## Funcionalidades

Entregue em oito fatias verticais, cada uma com backend, tela e invariantes no banco:

| # | Fatia | O que faz | Invariantes no banco |
|---|---|---|---|
| 1 | **Núcleo de pátio** | cadastro, mapa, gate-in/out, vaga, doca, dwell | `EXCLUDE` de vaga e de veículo, visita aberta única, trilha append-only |
| 2 | **Agendamento** | janela de doca com capacidade finita, prioridade como dado, portal do transportador | `EXCLUDE` de janela por doca e por veículo, versão otimista, parada de planta |
| 3 | **Balança** | driver serial/TCP + simulador, bruto/tara/líquido, conferência com a NF-e, antifraude | ticket fechado imutável, líquido derivado, pesagem manual com segundo fator |
| 4 | **Portaria automática** | LPR, QR, RFID, checklist, triagem, comando de cancela com permissivo | comando exige permissivo + autorizador, checklist bloqueia |
| 5 | **Movimentação e doca** | fila de manobra por custo, aceite, confirmação por leitura, cronometria, pendências | tarefa ativa única, confirmação com evidência, doca exclusiva, segregação de função |
| 6 | **IoT / OT** | modelo de informação único, telemetria, saúde dos dispositivos, operação degradada, RTLS opcional | qualidade obrigatória, evento idempotente, lote de edge único |
| 7 | **Torre e IA** | agente de regras que gera propostas com impacto, aprovação humana, alarmes ISA-18.2 | proposta só executa aprovada e no prazo |
| 8 | **Integrações** | outbox transacional, documentos fiscais (NF-e com DV), notificações com opt-out, BI | outbox deduplicado, idempotência por chave, opt-out respeitado |

E mais:

- **Login e usuários** no próprio PostgreSQL (`YARD_AUTH_MODE=local`) ou via **Keycloak/OIDC**; perfis por rota, senha provisória com troca obrigatória, bloqueio por tentativas e trilha de acesso. Só o admin master mexe em administradores.
- **Vários pátios** com **editor visual**: novo pátio com layout inicial gerado (zonas, vagas, docas, guaritas, balanças), CRUD de cada elemento e gerador de vagas em grade.
- **Interface** em pt-BR e en-US (nenhuma string literal em componente), tema claro / escuro / **HMI** e densidade compacta / padrão / toque — troca de token, sem forkar componente. Cor é anormalidade (ISA-101).
- **PWA** instalável no celular e no desktop; o service worker nunca guarda dado operacional.
- **Página inicial** com **gêmeo digital 3D** do pátio (Three.js + GSAP), carregada sob demanda.
- **Simulador de campo** (LPR, cancela e balança falsos) para demonstração sem hardware nenhum.

## Telas

| Torre de controle | Agendamento de docas |
|---|---|
| ![Torre com KPIs, mapa do pátio por zona, docas e fila ao vivo](.github/telas/torre-de-controle.png) | ![Gantt de docas com janelas, capacidade finita e doca bloqueada](.github/telas/agendamento-docas.png) |
| **Totem da guarita** | **Página inicial (gêmeo digital 3D)** |
| ![Fluxo guiado: identificar veículo, checklist, liberar cancela](.github/telas/totem-guarita.png) | ![Página pública com o pátio em 3D](.github/telas/pagina-inicial.jpg) |

> Capturas feitas numa instância local com o **seed de demonstração** (planta, transportadoras, motoristas e placas gerados — nada real).

| Tela | Rota | O que mostra |
|---|---|---|
| Torre de controle | `/` | mapa SVG, 11 KPIs, fila ao vivo, arrastar veículo entre vagas |
| Guarita | `/gate` | gate-in manual, fila de triagem, liberar para pátio, registrar saída |
| Totem | `/kiosk` | fluxo guiado passo a passo, checklist, cancela com permissivo |
| Agendamento | `/scheduling` | gantt de docas, arrastar para reprogramar, conflito antes do drop |
| Balança | `/weighing` | peso ao vivo, captura bruto/tara, divergência × NF-e, hash |
| Manobra | `/moves` | fila por custo de movimento, aceite, confirmação por QR |
| Torre + IA | `/tower` | propostas com impacto, aprovação humana, alarmes ISA-18.2 |
| Visitas | `/visits` | tabela densa, busca, trilha de eventos append-only |
| Pátios / Usuários | `/admin/yards`, `/admin/users` | editor de pátio e gestão de acesso |
| Página inicial | `/inicio` | gêmeo digital 3D e apresentação |

## Arquitetura

```mermaid
flowchart LR
    subgraph Navegador["Navegador / totem / celular (PWA)"]
        WEB["apps/web<br/>React 19 + Vite + TS"]
        DS["packages/ds<br/>GPS//YARD design system"]
    end
    subgraph Campo["Campo (OT)"]
        DEV["LPR · RFID · cancela<br/>balança serial/TCP"]
        EDGE["MQTT Sparkplug B<br/>OPC UA"]
        SIM["simulador<br/>(demonstração)"]
    end
    subgraph API["apps/api — FastAPI (1 worker)"]
        MOD["módulos verticais<br/>yard · visits · scheduling · weighing<br/>gate · moves · iot · tower · integrations"]
        BUS["barramento in-process<br/>WebSocket / SSE"]
    end
    PG[("PostgreSQL 16+<br/>TimescaleDB · pgvector (opcionais em dev)<br/>invariantes, triggers, EXCLUDE")]
    IDP["Keycloak (OIDC)<br/>ou login local"]
    EXT["ERP · fiscal · notificações<br/>(outbox)"]

    WEB --- DS
    WEB -- "/api · /ws · /sse · /portal" --> MOD
    MOD --> BUS --> WEB
    MOD --> PG
    DEV --> EDGE --> MOD
    SIM -- "pela API" --> MOD
    MOD -. "token" .- IDP
    MOD -- "outbox" --> EXT
```

- **Um worker de propósito**: o barramento de eventos da torre é in-process — dois workers seriam duas torres que não se veem.
- **A API não fala português nem inglês**: erro é `{"error":{"code":"ERR_YARD_…","params":{…}}}`; o texto vive em `apps/web/src/locales/*/errors.json`.
- **Migration só anda para frente** (13 migrations Alembic); cada uma lista no cabeçalho os invariantes que cria.
- **Em produção** a API recusa subir com autenticação aberta, simulador ligado, CORS em localhost ou credencial padrão de banco (`Settings.validate_production`); as rotas de simulação nem são registradas e seeds/simulador recusam rodar com `YARD_ENV=prod`.

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | React 19, Vite 6, TypeScript strict, TanStack Query, Zustand, i18next, Three.js + GSAP (página inicial), PWA |
| Design system | `packages/ds` — tokens, primitivos e blocos industriais (`YardMap`, `DockTimeline`, `ScaleDisplay`, `StepFlow`, `AlarmList`…) com Storybook |
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, Pydantic v2 |
| Banco | PostgreSQL 16+ (TimescaleDB e pgvector opcionais no desenvolvimento) |
| Campo (opcional) | MQTT Sparkplug B, OPC UA (`asyncua`), serial (`pyserial`) |
| Identidade | login local (Postgres) ou Keycloak/OIDC |
| Implantação | systemd + Caddy (`deploy/vps/`) ou Docker Compose com Traefik + Keycloak (`docker-compose.prod.yml`) |

## Como rodar localmente

Requisitos: Python 3.12+, Node 20+ e PostgreSQL 16+ (ou Docker para subir o banco).

```bash
git clone https://github.com/SSBianchiplan/yard.git
cd yard

# 1. banco: Postgres 16 + TimescaleDB + pgvector na porta 5442 (usuário/senha "yard" só de desenvolvimento)
docker compose up -d db

# 2. API
cd apps/api
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m alembic upgrade head          # 13 migrations: schema, invariantes e triggers
python -m app.seed                      # 180 vagas, 24 docas, ~2.800 visitas, 46 em pátio
python -m app.seed_scheduling           # agenda de 3 dias, recursos, regras de prioridade
python -m app.seed_gate                 # 29 dispositivos, checklists, 400 identificações
python -m uvicorn app.main:app --reload # API em http://localhost:8000 (docs em /docs)

# 3. front (em outro terminal, na raiz do repositório)
npm install
npm run dev                             # app em http://localhost:5173
```

Sem configurar nada, a API sobe em `YARD_AUTH_MODE=open` (só fora de produção). Para testar o login local:

```bash
export YARD_AUTH_MODE=local
export YARD_AUTH_SECRET="$(openssl rand -hex 32)"
export YARD_MASTER_EMAIL=admin@exemplo.com
export YARD_MASTER_PASSWORD='SenhaExemplo123!'
python -m uvicorn app.main:app --reload
```

- Banco em outra porta/host? Exporte `YARD_DATABASE_URL` (ex.: `postgresql+asyncpg://usuario@localhost:5432/yard`). TimescaleDB e pgvector são opcionais em desenvolvimento: as migrations seguem sem eles.
- API em outra porta? `VITE_API_PROXY=http://localhost:8088 npm run dev`.
- **Pátio se mexendo sozinho**: `python -m app.simulator --api http://localhost:8000 --rate 12` emite chegadas pela API. `POST /api/v1/weighing/scales/SCALE-01/simulate?target_kg=42000` "sobe" um caminhão na balança; `POST /api/v1/iot/simulate` gera um tick de campo.
- **Design system**: `npm run storybook` abre http://localhost:6006.
- Rede corporativa que intercepta TLS do registry npm? Exporte a cadeia de certificados e aponte `NODE_EXTRA_CA_CERTS` para ela — não desligue a verificação.

### Testes e verificações

```bash
cd apps/api && python -m pytest -q     # 96 testes: invariantes, máquina de estados, auth (banco yard_test)
npm run i18n:check                     # chave faltando em algum locale ou literal em JSX quebra o build
npm run typecheck && npm run lint
cd apps/web
node scripts/responsive-check.mjs      # 4 dispositivos × 8 telas: overflow, alvo de toque, texto cortado
node scripts/smoke-ui.mjs              # abre modal, bloqueia checklist, cria janela, lê balança
node scripts/screenshot.mjs shots      # captura as telas para conferência visual
```

### Produção

- **VPS sem Docker** (como em yard.gplansis.com): venv + systemd + Caddy — veja [`deploy/vps/README.md`](deploy/vps/README.md). `deploy/vps/enviar.sh` faz o build (com o gate de i18n), envia por rsync e roda `instalar-remoto.sh` (banco, migrations, units, Caddy validado antes do reload).
- **Docker Compose**: `docker compose -f docker-compose.prod.yml --env-file .env.production up -d` sobe Traefik (TLS), Keycloak, API e front em nginx. Modelo em [`.env.production.example`](.env.production.example).

## Estrutura de pastas

```
yard/
├── apps/
│   ├── api/                    # FastAPI + SQLAlchemy async
│   │   ├── alembic/versions/   # 13 migrations (invariantes no cabeçalho de cada uma)
│   │   ├── app/core/           # config, banco, segurança, erros, eventos
│   │   ├── app/modules/        # auth, catalog, yard, yardconfig, visits, scheduling,
│   │   │                       # weighing, gate, moves, iot, tower, integrations, kpi
│   │   ├── app/seed*.py        # seed de demonstração (nenhuma tela nasce vazia)
│   │   ├── app/simulator.py    # simulador de campo
│   │   └── tests/              # 96 testes (pytest)
│   └── web/                    # React 19 + Vite + TS strict
│       ├── src/pages/          # telas (+ admin/ e landing/)
│       ├── src/locales/        # pt-BR e en-US
│       └── scripts/            # i18n, responsividade, smoke e capturas (Playwright)
├── packages/ds/                # GPS//YARD design system + Storybook
├── deploy/vps/                 # systemd, Caddy e scripts de publicação
├── docs/                       # especificação de produto e guia de uso
├── docker-compose.yml          # banco de desenvolvimento
├── docker-compose.prod.yml     # Traefik + Keycloak + API + web
└── ASSUNCOES.md                # decisões tomadas para não travar a construção
```

Documentação: [guia de uso, tela por tela](docs/GUIA-DE-USO.md) · [especificação do produto](docs/SPEC-PRODUTO.md) · [assunções](ASSUNCOES.md).

## Variáveis de ambiente

Todas com prefixo `YARD_` (lidas por `apps/api/app/core/config.py`, exceto as do simulador). Modelos: [`.env.example`](.env.example) e [`.env.production.example`](.env.production.example).

| Variável | Uso | Padrão |
|---|---|---|
| `YARD_DATABASE_URL` | Conexão async com o PostgreSQL | `postgresql+asyncpg://yard:yard@localhost:5442/yard` (só dev) |
| `YARD_ENV` | `dev`, `staging` ou `prod` (prod ativa as travas de produção) | `dev` |
| `YARD_PLANT_CODE`, `YARD_PLANT_TIMEZONE` | Planta e fuso | `PLANT-01`, `America/Sao_Paulo` |
| `YARD_CORS_ORIGINS` | Origens permitidas (separadas por vírgula) | `http://localhost:5173` |
| `YARD_AUTH_MODE` | `open` (só fora de prod), `local` ou `oidc` | `open` |
| `YARD_AUTH_SECRET` | Segredo do token no modo `local` (≥ 32 caracteres aleatórios) | — |
| `YARD_AUTH_TOKEN_HOURS`, `YARD_AUTH_MAX_FAILED_LOGINS`, `YARD_AUTH_LOCK_MINUTES` | Sessão e bloqueio | `12`, `5`, `15` |
| `YARD_MASTER_EMAIL`, `YARD_MASTER_NAME`, `YARD_MASTER_PASSWORD` | Admin master criado no primeiro boot (a senha só vale na criação) | — |
| `YARD_OIDC_ISSUER`, `YARD_OIDC_JWKS_URL`, `YARD_OIDC_AUDIENCE` | Keycloak/OIDC | realm `yard` em localhost |
| `YARD_FIELD_MODE` | `simulator` ou `live` | `simulator` |
| `YARD_MQTT_HOST`, `YARD_MQTT_PORT`, `YARD_MQTT_USERNAME`, `YARD_MQTT_PASSWORD`, `YARD_MQTT_GROUP_ID`, `YARD_MQTT_NODE_ID`, `YARD_MQTT_TLS` | Campo via MQTT Sparkplug B | — |
| `YARD_OPCUA_ENDPOINT`, `YARD_OPCUA_USERNAME`, `YARD_OPCUA_PASSWORD` | Campo via OPC UA | — |
| `YARD_SIM_EMAIL`, `YARD_SIM_PASSWORD`, `YARD_SIM_ROLES`, `YARD_SIM_RATE` | Conta de serviço e ritmo do simulador (deploy de demonstração) | — |
| `YARD_LOG_LEVEL`, `YARD_LOG_JSON` | Logs | `INFO`, `false` |
| `VITE_API_PROXY` | (front, dev) destino do proxy do Vite | `http://localhost:8000` |
| `VITE_YARD_WHATSAPP` | (front, build) número comercial do WhatsApp da página inicial, só dígitos com DDI; vazio = botões caem no e-mail | vazio |

Nunca versione `.env` ou `.env.production`.

## Contribua

O YARD é um projeto ambicioso: um sistema de pátio industrial aberto, com invariantes no banco, IA com freio de mão humano e campo de verdade (MQTT, OPC UA, balança serial). **Há espaço para muita gente** — de quem escreve um teste a quem tem uma balança na bancada.

**Por onde começar (boas primeiras issues):**
- 🔌 **Drivers de campo de produção**: MQTT Sparkplug B e OPC UA no lugar do simulador; drivers de balança de fabricantes comuns (protocolos serial/TCP).
- 🛰️ **RTLS real** (posição de veículo no pátio) sobre o modelo de informação que já existe.
- 🔗 **Conectores ERP** concretos (SAP, TOTVS, Sankhya, Odoo…) consumindo o outbox transacional.
- 🔐 **Portal do transportador** com identidade (Keycloak) — veja [ASSUNCOES.md](ASSUNCOES.md).
- 🌐 **Novos idiomas** (es-ES é o próximo natural): `src/locales/` + `npm run i18n:check`.
- ♿ **Acessibilidade** no totem e no celular; telas no tema HMI.
- 🧹 **Zerar o `ruff check`** da API (hoje acusa pendências de estilo antigas, muitas com `--fix`).
- 🧪 **Testes** de UI no CI (Playwright) e **GitHub Actions** com pytest, ruff, typecheck, lint e i18n.
- 📚 **Documentação**: tutoriais de implantação, exemplos de layout de pátio.

Leia o [guia de contribuição](CONTRIBUTING.md), abra uma [issue](../../issues/new/choose) para combinar a ideia e mande seu pull request. Siga o [código de conduta](CODE_OF_CONDUCT.md). Encontrou uma falha de segurança? Veja a [política de segurança](SECURITY.md) — não abra issue pública.

## Licença

Código próprio sob a **[licença MIT](LICENSE)** — Copyright (c) 2026 GPlanSiS.

Nenhum código de terceiros está copiado no repositório; as dependências são instaladas por `npm` e `pip` e mantêm as próprias licenças — entre elas React, Vite, Three.js, i18next, Zustand, TanStack Query, FastAPI, SQLAlchemy, Alembic, Pydantic (MIT), asyncpg (Apache-2.0), **GSAP** (licença própria "Standard 'no charge' License" da GreenSock/Webflow) e, no extra opcional de campo, **asyncua** (LGPL-3.0).

## Créditos

Desenvolvido pela **[GPlanSiS|Group](https://gplansis.com)** · contato: [contato@gplansis.com](mailto:contato@gplansis.com)

<p align="center"><a href="https://yard.gplansis.com"><b>yard.gplansis.com</b></a></p>
