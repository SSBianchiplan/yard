# Assunções

Dúvida de negócio não para o código: vira assunção documentada aqui, marcada com
`// ASSUNÇÃO:` no ponto do código, e segue. Cada linha é revisável pelo dono do processo.

| # | Assunção | Onde vive | Revisar quando |
|---|---|---|---|
| 1 | Uma planta por instância. Multi-planta vira tenant na Fatia 8. | `core/config.py`, `service._plant_id` | segunda planta entrar |
| 2 | Fuso de exibição é o da planta (`America/Sao_Paulo`), nunca o do navegador. | `lib/format.ts` | planta em outro fuso |
| 3 | CNH vencida **bloqueia** gate-in. Liberação excepcional é override auditado de supervisor (Fatia 4). | `visits/service.gate_in` | EHS definir política de exceção |
| 4 | Veículo e motorista precisam existir no cadastro antes do gate-in; não há auto-cadastro na guarita. | `visits/service.gate_in` | pré-cadastro do portal (Fatia 2) |
| 5 | Alocação automática de vaga é "primeira vaga livre por código". Otimização por custo de movimento chega na Fatia 7, sempre com confirmação humana. | `visits/service.assign_slot` | regra de compatibilidade produto × zona entrar |
| 6 | Dwell total = `gate_out_at − arrived_at` (conta a espera na guarita, não só o tempo em pátio). | `visits/service.dwell_seconds` | contrato de demurrage definir outra base |
| 7 | Compatibilidade produto × zona e veículo × vaga ainda não é aplicada; o modelo já tem `kind` em vaga e `hazardous` em produto. | `yard/models.py` | Fatia 2 (reserva) ou antes, se houver produto perigoso |
| 8 | Um veículo tem no máximo uma visita aberta. Composição cavalo + carreta é uma visita só, com `trailer_plate` no veículo. | índice `uq_visit_open_vehicle` | pátio de ativos (carreta desacoplada) entrar |
| 9 | Pendência de saída é um campo único (`blocked_reason_code`). Vira tabela `quality_hold`/fiscal na Fatia 5/7. | `visit` | primeira pendência com múltiplas origens |
| 10 | Retenção de imagem de LPR/pesagem: 90 dias, depois anonimização. Placa isolada mantida 12 meses por necessidade fiscal. | `docs/SPEC-PRODUTO.md` §3.11 | DPO da planta revisar |
| 11 | TimescaleDB e pgvector são opcionais no dev local (a migration degrada para tabela comum) e obrigatórios em produção. | `alembic/0001_fatia1_core.py` | preparar ambiente de produção |
| 12 | Autenticação ainda não está ligada: `actor` chega como string do cliente. Keycloak entra na Fatia 2, antes de qualquer exposição externa. | `visits/schemas.py` | **antes** de expor o portal do transportador |
| 13 | Barramento de eventos é in-process (`core/events.Hub`). O contrato `publish(topic, payload)` não muda quando virar MQTT/NATS na Fatia 6. | `core/events.py` | segundo processo de API subir |
| 14 | Unidade de exibição de peso é configurável (kg/t/lb); o dado trafega sempre em kg. | `lib/format.ts` | cliente exigir lb como padrão |
| 15 | Seed usa 7 dias × 400 movimentos e 46 veículos no retrato do agora — abaixo do pico de 60 do cenário-referência, para deixar folga de vaga na demonstração. | `app/seed.py` | teste de carga do pico |
| 16 | Tolerância de chegada: 2h antes e 4h depois da janela do agendamento; fora disso é exceção de triagem. | `visits/service.gate_in` | operação definir SLA de tolerância |
| 17 | Portal do transportador exige 2h de antecedência para auto-agendamento. | `scheduling/portal.py` | contrato de SLA com transportadoras |
| 18 | LPR abaixo de 0,85 de confiança não libera sozinha (o mesmo número está no CHECK da migration 0004). | `gate/service.LPR_THRESHOLD` | calibração da câmera em campo |
| 19 | Reentrada da mesma placa na mesma balança em menos de 10 min é suspeita e exige justificativa. | `weighing/service.REENTRY_WINDOW` | operação com dupla pesagem legítima frequente |
| 20 | Tolerância padrão de divergência peso × NF-e: 0,5%. Configurável por ticket. | `weighing/service`, `weighing_ticket.tolerance_pct` | contrato comercial por produto |
| 21 | Custo de movimento usa distância euclidiana; rota real com sentido de tráfego entra com o mapa de vias. | `moves/service._distance` | pátio com circulação complexa |
| 22 | Proposta de IA vale 10 minutos; depois disso expira sozinha. | `tower/service.PROPOSAL_TTL` | torre pedir janela maior |
| 23 | Propostas da IA são heurísticas explícitas (`heuristic-v1`), não modelo estatístico — sugestão que ninguém explica é sugestão que ninguém aprova. | `tower/service.generate_proposals` | houver histórico suficiente para treinar |
| 24 | Permissivo do CLP vem de sinal mapeado quando existe; sem sinal, o simulador responde (e nega ~4% das vezes). | `gate/service.read_permissive` | integração OPC UA/MQTT de produção |
| 25 | Retenção de telemetria: compressão em 7 dias, retenção 180 dias (políticas Timescale). | migration `0006` | volume real medido |
| 26 | Publicação do outbox vai para o barramento interno enquanto não há endpoint configurado. | `integrations/service._publish` | primeiro conector ERP real |
| 27 | Simulador tem dois modos: direto no banco (popular rápido) e `--api` (device de verdade). Só o modo `--api` alimenta o WebSocket, porque o barramento é in-process. | `app/simulator.py` | barramento virar MQTT/NATS (Fatia 6 em produção) |
| 28 | Porta da API no front vem de `VITE_API_PROXY`, com 8000 como padrão. | `apps/web/vite.config.ts` | ambiente padronizar porta |
| 29 | Em modo `local` o WebSocket exige o token no subprotocolo (`yard.bearer`, não na query — não vai para log de acesso). Em `oidc` ainda não valida. | `main.yard_socket` | fluxo OIDC no front |
| 30 | Em modo `open` (desenvolvimento) o ator vem do cabeçalho `X-Dev-Actor`; em produção, só do token. | `core/security.current_principal` | nunca: `open` é recusado em prod |
| 31 | Layout do pátio no seed é fictício (2×3 zonas, docas na parede sul). O mapa real entra por importação de DWG/GeoJSON. | `app/seed.py`, spec §3.5 | planta fornecer a planta baixa |
| 32 | Prioridade de coluna nas tabelas: `essential` sempre visível, `secondary` some no celular, `detail` some no tablet. | `packages/ds/.../DataTable.tsx` | operação pedir outra coluna no celular |
| 33 | Autenticação `local` (usuários no Postgres, scrypt, JWT HS256 de 12 h) para instalação sem Keycloak. Perfil e situação são relidos do banco a cada requisição: desativar corta o acesso na hora. | `modules/auth`, migration `0013` | planta exigir SSO corporativo (usar `oidc`) |
| 34 | Existe um único admin master, protegido no banco (não desativa, não perde `yard.admin`, não é apagado). Só ele cria ou altera administradores. | migration `0013`, `auth/service` | organização pedir mais de um master |
| 35 | 5 senhas erradas bloqueiam a conta por 15 min; senha mínima de 10 caracteres com letra e número. | `core/config` (`auth_*`), `auth/passwords` | política de senha corporativa |
| 36 | Código de zona/vaga/doca/guarita/balança continua **único no sistema inteiro**, não por pátio: ~20 pontos da operação acham o elemento pelo código. O assistente de novo pátio prefixa tudo com o código do pátio. | `yardconfig/service` | escopo por pátio em todos os módulos |
| 37 | Com vários pátios, a visita pertence ao pátio da guarita de entrada, e a alocação automática só procura vaga daquele pátio. KPIs, fila e agendamento ainda somam todos os pátios. | `visits/service.gate_in/assign_slot` | cliente operar dois pátios reais na mesma instância |
| 38 | Elemento de pátio com histórico não se apaga (FK recusa → `ERR_YARD_CONFIG_IN_USE`); a saída é bloquear ou pôr em manutenção. | `yardconfig/service.delete_element` | — é de propósito |
| 39 | Tipo `cold_chain` (vaga com tomada para baú refrigerado) existe no cadastro e no mapa, mas a alocação automática ainda não casa tipo de vaga com tipo de carga. | migration `0013`, `domain/enums` | regra de compatibilidade vaga × produto |
| 40 | O projeto demo é uma planta de alimentos fictícia (nomes de transportadoras e produtos inventados). | `app/seed.py` | — |
