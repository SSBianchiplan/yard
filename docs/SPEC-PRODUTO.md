# GPlanSiS | YARD — Especificação de Produto

**Yard Operating System (YOS), não Yard Management System.**
A diferença é operacional, não semântica: um YMS registra o que aconteceu; o YOS **decide e comanda o próximo movimento**. Dado nasce de sensor e evento; humano trata exceção; torre de controle atua fisicamente com trilha auditada; tudo trafega em barramento de eventos sob contrato de API versionado.

| Eixo | YMS convencional | GPlanSiS \| YARD (YOS) |
|---|---|---|
| Papel do sistema | registra e mostra | decide e comanda o próximo movimento |
| Origem do dado | digitação | sensor, evento de campo, LPR, balança, CLP |
| Papel do humano | digitar tudo | tratar exceção e aprovar ação física |
| Torre de controle | dashboard | atuação física auditada (cancela, semáforo, sequência) |
| Integração | arquivo/batch | barramento de eventos + API versionada e idempotente |

## 0. Escopo de pátio coberto

1. **Recebimento de matéria-prima** — granel sólido e líquido, moega/silo, balança rodoviária, dupla pesagem.
2. **Expedição de produto acabado** — paletizado, contêiner, carga viva, carga projeto.
3. **Pátio de ativos e equipamentos** — carretas estacionadas, dollies, cavalos mecânicos, contêineres, equipamento de terceiro, WIP de grande porte em manufatura pesada.
4. **Pátio misto de planta** — visitante, prestador, frota própria, coleta de resíduo, manutenção.

### Cenário-referência de dimensionamento (mínimo, é o que o seed reproduz)

| Dimensão | Valor |
|---|---|
| Plantas | 1 |
| Guaritas | 3 |
| Balanças rodoviárias | 2 |
| Docas | 24 |
| Vagas demarcadas | 180 |
| Movimentos de veículo/dia | 400 |
| Pico simultâneo em pátio | 60 veículos |
| Regime | 24×7 |

Consequências de arquitetura que saem direto desse cenário: ~2.400 eventos de domínio/dia só do fluxo feliz (6 por visita), pico de ~40 req/s em portaria, WebSocket com 60 posições mudando de estado por minuto na torre, retenção de telemetria em hypertable com compressão a partir de 7 dias.

---

# 1. Blocos funcionais

Cada bloco abaixo é especificado em oito faces: **Entidades · Estados · Eventos · Regras · Invariantes de banco · API · Tela · KPI**. Invariante de banco é o que fica em `CHECK`, `EXCLUDE`, índice único parcial ou trigger — barato lá, caro na aplicação.

---

## 3.1 Cadastro e pré-cadastro

### Entidades
`driver` (motorista), `vehicle` (cavalo/reboque: placa, eixos, tara, comprimento, refrigerado, tanque), `carrier` (transportadora), `supplier`, `customer`, `asset` (carreta, dolly, contêiner, equipamento), `freight_contract`, `product` (carga, classe de risco ONU, embalagem), `operation_type`, `document` (documento de validade), `document_kind`.

`document` é entidade própria, polimórfica por `owner_kind` + `owner_id` (`driver` | `vehicle` | `carrier` | `asset`), com `kind_code`, `number`, `issued_on`, `expires_on`, `file_ref`, `status`.

Tipos documentais mínimos: `CNH`, `ASO`, `NR_TRAINING` (NR-11, NR-20, NR-35), `INSURANCE`, `CRLV`, `HAZMAT_LICENSE`, `TANK_REPORT` (laudo de tanque), `ANTT_RNTRC`.

### Estados
`document.status`: `valid` → `expiring` (≤ 30 dias) → `expired` → `suspended` → `waived` (dispensa formal com aprovador).
`driver.status` / `vehicle.status` / `carrier.status`: `active` → `blocked` → `inactive`. `blocked` carrega `blocked_reason_code`, nunca texto livre.

### Eventos
`document.registered`, `document.renewed`, `document.expired` (job diário + verificação no ponto de uso), `document.waived`, `party.blocked`, `party.unblocked`.

### Regras
- **Regra dura:** documento vencido ⇒ bloqueio de agendamento **e** de gate-in, com motivo rastreável (`ERR_YARD_DOC_EXPIRED` + `{kind, owner, expires_on}`).
- Dispensa (`waived`) exige perfil `yard.supervisor`, justificativa obrigatória e validade máxima de 24 h; nasce como exceção auditada, nunca como estado silencioso.
- Validade é sempre verificada **no instante do uso** (agendamento, gate-in), nunca só por job — job apenas antecipa o aviso.
- Pré-cadastro pelo portal do transportador cria registros em `pending_review`; só vira `active` após conferência ou regra automática de documento válido.

### Invariantes de banco
```sql
-- documento não tem vigência invertida
CONSTRAINT ck_document_period CHECK (expires_on IS NULL OR expires_on >= issued_on)
-- um documento vigente por (dono, tipo)
CREATE UNIQUE INDEX uq_document_owner_kind_active
  ON document(owner_kind, owner_id, kind_code) WHERE status IN ('valid','expiring');
-- dispensa exige aprovador e prazo
CONSTRAINT ck_document_waiver CHECK (
  status <> 'waived' OR (waived_by IS NOT NULL AND waived_until IS NOT NULL))
-- placa normalizada (sem hífen, maiúscula) para casar com LPR
CONSTRAINT ck_vehicle_plate_norm CHECK (plate = upper(plate) AND plate !~ '[^A-Z0-9]')
```

### API
```
GET/POST/PATCH /api/v1/catalog/{drivers|vehicles|carriers|assets|products|operation-types}
GET   /api/v1/catalog/documents?owner_kind=&owner_id=&status=
POST  /api/v1/catalog/documents            # registro/renovação
POST  /api/v1/catalog/documents/{id}/waive # exige perfil supervisor
GET   /api/v1/catalog/compliance/{owner_kind}/{owner_id}  # semáforo consolidado
```

### Tela
`ListWorkspace` de cadastro com filtro salvo e coluna de conformidade (pastilha verde/âmbar/vermelha por tipo documental). `DetailWorkspace` com aba Documentos mostrando vigência em barra temporal. Bloqueio aparece como `AlarmBanner`, não como toast que some.

### KPI
% de cadastros com documentação 100 % vigente · nº de bloqueios por documento vencido/dia · lead time de regularização · % de gate-in barrado por documento.

---

## 3.2 Agendamento (appointment / janela de doca)

### Entidades
`appointment`, `dock_slot_template` (grade de janelas por doca/turno), `resource` (empilhadeira, moega, equipe, operador de ponte), `resource_capacity`, `shift_calendar`, `plant_stoppage` (parada de planta/feriado), `priority_rule`, `appointment_change_log`.

### Estados
`appointment`: `draft` → `requested` → `confirmed` → `checked_in` → `in_progress` → `completed`; ramos `cancelled`, `no_show`, `rescheduled`.
`dock_window`: `open` → `reserved` → `full` → `blocked`.

### Eventos
`appointment.requested`, `.confirmed`, `.rescheduled`, `.cancelled`, `.no_show`, `slot.reserved`, `slot.released`, `capacity.exhausted`, `priority.applied`.

### Regras
- Slot por **doca × tipo de carga × recurso de descarga**, com capacidade finita; confirmar consome capacidade dos três eixos ao mesmo tempo — se qualquer um estourar, não confirma.
- Calendário de turno, feriado e parada de planta fecham janelas; janela fechada não aceita agendamento nem reprogramação.
- **Prioridade** por regra ordenada: perecível > cross-dock > carga programada de produção (vinculada a OP com data firme) > veículo cativo > demurrage em curso > ordem de chegada. A regra é dado (`priority_rule`), não `if` no código.
- Reprogramação sempre grava rastro: quem, quando, por quê (código de motivo), e **impacto em fila** calculado no momento (nº de agendamentos deslocados, minutos de atraso projetado).
- **Edição concorrente segura:** controle otimista por `version` no agregado + reserva transacional da janela. Dois programadores no mesmo calendário nunca sobrescrevem em silêncio: o segundo recebe `ERR_YARD_APPOINTMENT_STALE` com o estado atual para merge na tela.
- Confirmação reserva vaga (ver 3.5) quando o tipo de operação exigir espera em pátio.

### Invariantes de banco
```sql
-- doca não tem dois agendamentos sobrepostos
CONSTRAINT ex_appointment_dock EXCLUDE USING gist (
  dock_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
  WHERE (state IN ('confirmed','checked_in','in_progress'))
-- veículo não tem dois agendamentos sobrepostos
CONSTRAINT ex_appointment_vehicle EXCLUDE USING gist (
  vehicle_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
  WHERE (state IN ('confirmed','checked_in','in_progress'))
CONSTRAINT ck_appointment_window CHECK (ends_at > starts_at)
-- capacidade de recurso nunca negativa
CONSTRAINT ck_resource_capacity CHECK (remaining >= 0)
-- concorrência otimista
CONSTRAINT ck_appointment_version CHECK (version >= 1)
```

### API
```
GET  /api/v1/scheduling/availability?dock=&from=&to=&operation_type=&resource=
POST /api/v1/scheduling/appointments                 # If-Match / version obrigatório no PATCH
PATCH /api/v1/scheduling/appointments/{id}           # 409 ERR_YARD_APPOINTMENT_STALE
POST /api/v1/scheduling/appointments/{id}/reschedule # exige reason_code
POST /api/v1/scheduling/appointments/{id}/cancel
GET  /api/v1/scheduling/appointments/{id}/impact     # simula impacto em fila
# Portal do transportador (audiência externa, escopo reduzido, rate limit próprio)
POST /portal/v1/appointments        POST /portal/v1/appointments/{id}/documents
```

### Tela
`DockTimeline` (gantt de docas, drag para reagendar, colisão destacada antes do drop), calendário de turno, fila de solicitações pendentes, painel de impacto ao reprogramar. Portal do transportador em `KioskFlow` simplificado.

### KPI
Aderência ao agendamento (chegada dentro da janela ± tolerância) · taxa de no-show · taxa de reprogramação e motivo dominante · ocupação de janela ofertada vs. consumida · lead time de confirmação.

---

## 3.3 Guarita / gate-in e gate-out

### Entidades
`gate`, `gate_lane`, `visit` (agregado central), `checklist_template`, `checklist_answer`, `identification_event` (LPR/QR/RFID/crachá/digitação), `escort` (acompanhante/ajudante/visitante), `access_command` (comando físico emitido).

### Estados
`visit`: `expected` → `at_gate_in` → `in_yard` → `at_dock` → `at_gate_out` → `departed`; ramos `rejected`, `queued` (sem agendamento, aguardando triagem).
`identification`: `captured` → `matched` → `ambiguous` → `manual_override`.
`access_command`: `requested` → `permitted` → `sent` → `acknowledged` → `failed` | `denied_by_plc`.

### Eventos
`gate.vehicle_detected` (laço/fotocélula), `gate.plate_read` (LPR com `confidence`), `gate.qr_scanned`, `gate.tag_read`, `gate.manual_entry`, `checklist.completed`, `gate.screening_decided`, `gate.barrier_open_requested`, `gate.barrier_opened`, `gate.barrier_denied`, `visit.gate_in`, `visit.gate_out`, `visit.rejected`.

### Regras
- Identificação por **LPR/OCR, QR do agendamento, RFID/TAG, crachá ou digitação de exceção**. Digitação é exceção rastreada: entra no KPI de exceção manual e exige `actor`.
- LPR abaixo do limiar de confiança (`< 0.85`, ajustável por guarita) **não libera sozinha** — cai para conferência humana com a imagem ao lado.
- **Checklist digital** por tipo de operação e carga: EPI, extintor, amarração, placa de produto perigoso, lacre, vazamento, estado do pneu. Item reprovado ⇒ `visit.rejected` ou fila de tratamento, conforme severidade do item.
- **Triagem automática:** agendamento válido e documentação vigente ⇒ destino calculado (vaga ou doca direta); sem agendamento ⇒ `queued` ou recusa conforme política do tipo de operação.
- **Comando físico só depois da regra satisfeita** e do permissivo do CLP (ver 3.8). Nenhuma rota de código abre cancela fora de `access_command`.
- Autoatendimento do motorista (totem, QR, WhatsApp) com **fallback de guarda humano** sempre disponível — indisponibilidade de canal nunca trava o pátio.
- Acompanhante, ajudante e visitante são registrados individualmente e entram na lista de emergência (3.11).

### Invariantes de banco
```sql
-- um veículo tem no máximo uma visita aberta
CREATE UNIQUE INDEX uq_visit_open_vehicle ON visit(vehicle_id)
  WHERE state IN ('at_gate_in','in_yard','at_dock','at_gate_out');
CONSTRAINT ck_visit_timeline CHECK (
  (gate_in_at IS NULL OR gate_in_at >= arrived_at) AND
  (gate_out_at IS NULL OR gate_in_at IS NULL OR gate_out_at >= gate_in_at))
-- saída não ocorre com pendência aberta
CONSTRAINT ck_visit_exit_not_blocked CHECK (state <> 'departed' OR blocked_reason_code IS NULL)
-- comando físico exige permissivo registrado
CONSTRAINT ck_access_command_permit CHECK (
  state <> 'sent' OR (plc_permissive = true AND authorized_by IS NOT NULL))
-- trilha append-only
CREATE TRIGGER trg_visit_event_append_only BEFORE UPDATE OR DELETE ON visit_event
  FOR EACH ROW EXECUTE FUNCTION yard_deny_mutation();
```

### API
```
POST /api/v1/visits/gate-in           POST /api/v1/visits/{id}/gate-out
POST /api/v1/visits/{id}/checklist    POST /api/v1/visits/{id}/reject
POST /api/v1/gates/{code}/identify    # LPR/QR/RFID/manual → candidatos + confiança
POST /api/v1/gates/{code}/command     # {device, action, visit_id} → access_command
GET  /api/v1/gates/{code}/queue       WS /ws/yard (fila e mapa ao vivo)
```

### Tela
`KioskFlow` em passo único por tela (padrão Tulip, alvo 44 px, usável com luva): identificar → conferir documento → checklist → destino → liberar. Fila de portaria ao vivo em `OperationalConsole`, com foto do LPR e botão de comando físico que só habilita com permissivo verde.

### KPI
Tempo de gate-in (detecção → cancela aberta) · % de identificação automática vs. digitada · taxa de recusa por motivo · fila média e de pico na guarita · tempo de checklist.

---

## 3.4 Balança e pesagem

### Entidades
`scale`, `scale_reading` (leitura bruta do indicador, alta frequência), `weighing_ticket`, `weighing_item`, `tare_record` (tara fixa vs. aferida), `axle_weight`, `weighing_image`, `weighing_override`.

### Estados
`weighing_ticket`: `open` → `first_weight` → `second_weight` → `closed` → `cancelled` (com motivo e aprovador).
`scale_reading`: `unstable` → `stable` → `captured`.
`scale` (dispositivo): `online` → `degraded` → `offline`.

### Eventos
`scale.reading` (contínuo), `scale.stable`, `scale.captured`, `weighing.first_weight`, `weighing.second_weight`, `weighing.closed`, `weighing.divergence_detected`, `weighing.manual_entry`, `weighing.reprint`.

### Regras
- Integração com indicador via **RS-232 e TCP/IP**, múltiplas balanças simultâneas, cada uma com driver e protocolo próprios (Toledo, Filizola, Alfa, Líder) atrás de uma interface única.
- Bruto / tara / líquido; **tara fixa cadastrada vs. tara aferida** — divergência acima da tolerância marca o ticket e exige decisão.
- Dupla pesagem e pesagem por eixo quando o tipo de operação exigir.
- **Antifraude:** captura de imagem no instante do peso, detecção de peso instável (janela de leitura sem variação além de ±X kg por N segundos), veículo mal posicionado (laço/fotocélula fora de faixa), reentrada suspeita (mesma placa, mesma balança, intervalo curto), pesagem manual exigindo justificativa **e segundo fator** (segundo usuário autorizado).
- Conferência **peso × documento fiscal** (NF-e/romaneio): divergência acima da tolerância ⇒ `blocked_reason_code` na visita ⇒ saída bloqueada.
- Ticket com **hash de integridade** (SHA-256 do payload canônico) e reimpressão auditada com contador.

### Invariantes de banco
```sql
-- ticket fechado é imutável
CREATE TRIGGER trg_weighing_ticket_immutable BEFORE UPDATE ON weighing_ticket
  FOR EACH ROW WHEN (OLD.state = 'closed') EXECUTE FUNCTION yard_deny_mutation();
CONSTRAINT ck_weighing_net CHECK (net_kg IS NULL OR net_kg = gross_kg - tare_kg)
CONSTRAINT ck_weighing_positive CHECK (gross_kg > 0 AND tare_kg > 0 AND gross_kg >= tare_kg)
CONSTRAINT ck_weighing_closed_hash CHECK (state <> 'closed' OR integrity_hash IS NOT NULL)
-- peso manual exige justificativa e segundo fator
CONSTRAINT ck_weighing_manual CHECK (
  source <> 'manual' OR (reason_code IS NOT NULL AND second_factor_user_id IS NOT NULL))
-- imagem obrigatória no instante do peso
CONSTRAINT ck_weighing_image CHECK (state <> 'closed' OR image_ref IS NOT NULL)
```

### API
```
GET  /api/v1/scales                    GET /api/v1/scales/{code}/live   # SSE da leitura
POST /api/v1/weighings                 # abre ticket
POST /api/v1/weighings/{id}/capture    # captura peso estável + imagem
POST /api/v1/weighings/{id}/close      # calcula líquido, confere com NF-e, gera hash
POST /api/v1/weighings/{id}/reprint    # auditado
POST /api/v1/weighings/{id}/cancel     # exige reason_code + perfil
```

### Tela
`ScaleDisplay` em display grande com indicador de estabilidade e câmera ao lado; passo único por operação; divergência peso × NF-e aparece como `AlarmBanner` bloqueante, com o número do documento fiscal em destaque.

### KPI
Divergência média de pesagem (kg e %) · % de pesagem manual · tempo médio de pesagem · nº de reentradas suspeitas · disponibilidade da balança · tickets cancelados por motivo.

---

## 3.5 Mapa de pátio e ocupação

### Entidades
`zone`, `slot` (vaga), `dock`, `hopper` (moega), `risk_area`, `traffic_route` (com sentido), `slot_occupancy`, `slot_reservation`, `compatibility_rule`.

### Estados
Posição (`slot` / `dock`): `free` → `reserved` → `occupied` → `blocked` → `maintenance`.

### Eventos
`slot.reserved`, `slot.assigned`, `slot.released`, `slot.blocked`, `slot.deviation_detected`, `map.version_published`.

### Regras
- Mapa digital 2D georreferenciado, **importável de DWG/planta baixa** (conversão para geometria própria em metros; versão do mapa é dado, e mudança de layout publica nova versão sem apagar histórico).
- Estado de cada posição em tempo real, com **estado de dado explícito** (fresco / obsoleto / sem comunicação) quando a fonte for sensor.
- **Regras de alocação** como dado (`compatibility_rule`): produto × zona (perigoso afastado, alimentício separado), veículo × vaga (comprimento, refrigerado com tomada, coberto vs. céu aberto), zona × operação.
- Reserva de vaga na **aprovação do agendamento**; liberação automática no gate-out ou por timeout de reserva.
- Alocação automática é sugestão na Fatia 1–5 e vira proposta de IA na Fatia 7 — sempre com confirmação humana antes de gerar comando físico.

### Invariantes de banco
```sql
-- veículo não ocupa duas vagas; vaga não recebe duas ocupações sobrepostas
CONSTRAINT ex_slot_occupancy_slot    EXCLUDE USING gist (slot_id    WITH =, period WITH &&)
CONSTRAINT ex_slot_occupancy_vehicle EXCLUDE USING gist (vehicle_id WITH =, period WITH &&)
-- reserva também é exclusiva no tempo
CONSTRAINT ex_slot_reservation EXCLUDE USING gist (slot_id WITH =, period WITH &&)
  WHERE (state = 'active')
-- vaga bloqueada/manutenção não recebe ocupação (trigger)
CREATE TRIGGER trg_slot_occupancy_slot_available BEFORE INSERT ON slot_occupancy ...
-- compatibilidade obrigatória quando produto é perigoso
CONSTRAINT ck_slot_hazmat CHECK (NOT hazardous_allowed OR distance_to_risk_area_m >= 30)
```

### API
```
GET  /api/v1/yard/map                 # snapshot completo (zonas, vagas, docas, guaritas, balanças)
GET  /api/v1/yard/slots?status=&zone=
POST /api/v1/visits/{id}/slot         # {slot_code} ou vazio = alocação automática
POST /api/v1/yard/slots/{code}/block  # exige reason_code
POST /api/v1/yard/map/import          # DWG/GeoJSON → nova versão de mapa
WS   /ws/yard                          # mudanças de ocupação ao vivo
```

### Tela
`YardMap` em SVG com zoom, pan, arrastar veículo entre vagas, cor **apenas** para anormalidade (ISA-101): vaga livre é cinza, ocupada é neutra com rótulo, bloqueada e dwell estourado é que ganham cor. Lista lateral sincronizada com o mapa.

### KPI
Ocupação de vagas (média, pico, por zona) · tempo médio de vaga ocupada · nº de vagas bloqueadas × motivo · taxa de alocação automática aceita sem alteração · desvio de posição detectado.

---

## 3.6 Movimentação (spotter / manobrista / yard jockey)

### Entidades
`move_task`, `move_assignment`, `spotter` (operador), `move_cost_matrix` (distância entre posições), `deviation`.

### Estados
`move_task`: `proposed` → `queued` → `assigned` → `accepted` → `in_progress` → `confirmed` → `cancelled` | `failed`.

### Eventos
`move.proposed`, `move.queued`, `move.assigned`, `move.accepted`, `move.started`, `move.confirmed` (por leitura), `move.deviation_detected`, `move.cancelled`.

### Regras
- Fila de tarefas com prioridade, atribuição e **aceite** no dispositivo móvel — aceite é ato do operador, não atribuição silenciosa.
- Sequenciamento por **custo de movimento**: distância na rota (não euclidiana), congestionamento da via, janela da doca, SLA da visita.
- **Confirmação por leitura** — QR da vaga, RTLS ou foto georreferenciada. Botão "concluído" digitado é exceção auditada, entra no KPI de exceção manual.
- **Detecção de desvio:** ativo estacionado em vaga diferente da atribuída gera `deviation` e tarefa corretiva, não apenas alerta.
- PWA offline-first: tarefa aceita fica no dispositivo; confirmação é enfileirada e reconciliada ao religar, com `client_event_id` idempotente.

### Invariantes de banco
```sql
-- uma tarefa ativa por ativo/veículo
CREATE UNIQUE INDEX uq_move_task_active ON move_task(vehicle_id)
  WHERE state IN ('queued','assigned','accepted','in_progress');
-- confirmação exige evidência
CONSTRAINT ck_move_confirmation CHECK (
  state <> 'confirmed' OR confirmation_kind IN ('qr','rtls','photo')
  OR (confirmation_kind = 'manual' AND reason_code IS NOT NULL))
-- idempotência do PWA offline
CREATE UNIQUE INDEX uq_move_client_event ON move_task(client_event_id);
```

### API
```
GET  /api/v1/moves/queue?spotter=            POST /api/v1/moves/{id}/accept
POST /api/v1/moves/{id}/start                POST /api/v1/moves/{id}/confirm  # payload com evidência
POST /api/v1/moves/sync                      # lote offline idempotente
GET  /api/v1/moves/deviations
```

### Tela
PWA `StepFlow` do manobrista: uma tarefa por tela, destino em mapa, botão grande de aceitar, câmera/scanner para confirmar. Torre vê a fila como `DataTable` densa com prioridade e tempo em fila.

### KPI
Movimentos por manobrista/hora · tempo de fila da tarefa · tempo de execução vs. custo estimado · % de confirmação por leitura vs. digitada · desvios detectados/dia.

---

## 3.7 Doca e operação de carga/descarga

### Entidades
`dock_visit` (ocupação da doca por uma visita), `dock_stage_timing`, `order_link` (OP / OC / pedido de venda / romaneio), `discrepancy`, `evidence` (foto), `quality_hold`.

### Estados
`dock_visit`: `scheduled` → `arrived` → `docked` (encostado) → `started` → `paused` → `finished` → `released`.
`discrepancy`: `open` → `under_review` → `accepted` → `rejected`.
`quality_hold` / pendência fiscal: `open` → `released`.

### Eventos
`dock.arrived`, `dock.docked`, `dock.started`, `dock.paused`, `dock.resumed`, `dock.finished`, `dock.released`, `discrepancy.reported`, `hold.opened`, `hold.released`.

### Regras
- Cronometria por etapa, cada transição com carimbo de tempo e origem (sensor de doca, operador, sistema).
- Vínculo obrigatório com ordem de produção, ordem de compra, pedido de venda ou romaneio conforme o tipo de operação — operação sem vínculo é exceção que exige motivo.
- Apontamento de divergência (avaria, falta, sobra, temperatura, umidade, lacre rompido) com **evidência fotográfica obrigatória**.
- **Bloqueio de saída** enquanto pendência de qualidade ou fiscal estiver aberta — o bloqueio vive na visita e é verificado no gate-out **e** no banco.
- Pausa exige motivo codificado (falta de mão de obra, falta de empilhadeira, chuva, aguardando documento) — é daí que sai a análise de gargalo.

### Invariantes de banco
```sql
-- doca não recebe dois veículos ao mesmo tempo
CONSTRAINT ex_dock_visit EXCLUDE USING gist (dock_id WITH =, period WITH &&)
CONSTRAINT ck_dock_stage_order CHECK (
  (docked_at IS NULL OR docked_at >= arrived_at) AND
  (started_at IS NULL OR started_at >= docked_at) AND
  (finished_at IS NULL OR finished_at >= started_at))
-- divergência exige evidência
CONSTRAINT ck_discrepancy_evidence CHECK (evidence_ref IS NOT NULL)
-- pendência aberta impede saída (checado também em visit)
CONSTRAINT ck_hold_release CHECK (state <> 'released' OR released_by IS NOT NULL)
CONSTRAINT ck_pause_reason CHECK (state <> 'paused' OR pause_reason_code IS NOT NULL)
```

### API
```
POST /api/v1/docks/{code}/dock-in     POST /api/v1/dock-visits/{id}/start
POST /api/v1/dock-visits/{id}/pause   POST /api/v1/dock-visits/{id}/resume
POST /api/v1/dock-visits/{id}/finish  POST /api/v1/dock-visits/{id}/release
POST /api/v1/dock-visits/{id}/discrepancies    # multipart com foto
POST /api/v1/visits/{id}/holds        DELETE /api/v1/visits/{id}/holds/{hold_id}
```

### Tela
`OperationalConsole` de doca: cronômetro por etapa, motivo de pausa em um toque, foto de divergência pela câmera do dispositivo, indicador de pendência que trava o botão de liberar.

### KPI
Utilização de doca · tempo por etapa (chegada→encosto, encosto→início, início→fim) · tempo de pausa por motivo · divergências por 1.000 movimentos · % de operação com vínculo de ordem.

---

## 3.8 Camada IoT / OT

### Entidades
`device`, `device_kind`, `device_health`, `signal` (tag normalizada no modelo de informação único), `signal_reading` (hypertable), `command` (atuação), `plc_permissive`, `edge_buffer_batch`.

Dispositivos cobertos: cancela, semáforo, laço indutivo, fotocélula, leitor RFID/UHF, câmera LPR, indicador de balança, sensor de nível de moega, botoeira, CLP de intertravamento.

### Estados
`device`: `online` → `degraded` → `offline` → `maintenance`.
Estado do **dado** (explícito na UI, exigência ISA-101): `fresh` | `stale` | `invalid` | `no_comm`.
`command`: `requested` → `permitted` → `sent` → `acknowledged` → `failed` | `denied_by_plc` | `timeout`.

### Eventos
`device.birth` / `device.death` (Sparkplug NBIRTH/DBIRTH/NDEATH/DDEATH), `signal.changed`, `device.health_changed`, `command.requested`, `command.permitted`, `command.sent`, `command.acknowledged`, `command.denied`, `edge.buffer_flushed`.

### Regras
- Barramento **MQTT Sparkplug B** e **OPC UA**; normalização em **modelo de informação único** (`plant/area/line/device/signal`), de modo que a aplicação nunca conheça endereço de tag do CLP.
- **Intertravamento de segurança:** o sistema **não substitui função de segurança**. Todo comando de atuação depende de permissivo do CLP lido como sinal, com estado de dado explícito. Permissivo `stale` ou `no_comm` ⇒ comando negado, nunca assumido.
- **Operação degradada:** o pátio opera com rede caída — buffer local no edge, fila de eventos persistente, reconciliação ao religar por `client_event_id`, sem perda de trilha. A ordem cronológica é reconstruída por `occurred_at` do campo, não pelo horário de chegada.
- **RTLS é camada opcional**: GPS/RTK em pátio aberto, UWB/BLE em área coberta, RFID em ponto fixo de gate. A arquitetura funciona sem RTLS e ganha precisão com ele — nenhuma regra de negócio pode depender de RTLS.
- Toda telemetria vai para hypertable com política de retenção e compressão; o dado operacional (visita, ticket) nunca depende da telemetria bruta para ser reconstruído.

### Invariantes de banco
```sql
-- comando físico só sai com permissivo verdadeiro e autorizador
CONSTRAINT ck_command_permissive CHECK (
  state NOT IN ('sent','acknowledged') OR (plc_permissive = true AND authorized_by IS NOT NULL))
-- comando originado de IA exige aprovação humana registrada
CONSTRAINT ck_command_ai_approval CHECK (
  origin <> 'ai' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
-- idempotência de evento de campo
CREATE UNIQUE INDEX uq_signal_reading_dedup ON signal_reading(device_id, signal_code, occurred_at);
-- leitura carrega qualidade; sem qualidade não entra
CONSTRAINT ck_signal_quality CHECK (quality IN ('good','stale','invalid','no_comm'))
SELECT create_hypertable('signal_reading','occurred_at', chunk_time_interval => interval '1 day');
```

### API
```
GET  /api/v1/devices                 GET /api/v1/devices/{id}/health
GET  /api/v1/signals/{code}/history?from=&to=
POST /api/v1/commands                # {device, action, origin, visit_id} → verifica permissivo
POST /api/v1/edge/sync               # lote do buffer local, idempotente
WS   /ws/field                       # telemetria ao vivo para a torre
```

### Tela
Painel de saúde de dispositivo (`AssetCard` com estado de dado e último contato), `AlarmList` ISA-18.2 com prioridade, reconhecimento, supressão e shelving. Comando físico sempre mostra o permissivo antes de habilitar o botão.

### KPI
Disponibilidade por dispositivo e por classe · latência de evento de campo (campo → banco) · nº de comandos negados por permissivo · eventos reconciliados após queda · % de leitura com qualidade `good`.

---

## 3.9 Integrações

### Entidades
`integration_endpoint`, `outbox_message`, `inbox_message`, `fiscal_document` (NF-e, CT-e, MDF-e, romaneio, ordem de coleta), `notification`, `delivery_log`, `api_client`.

### Estados
`outbox_message`: `pending` → `sent` → `acknowledged` → `failed` → `dead_letter`.
`fiscal_document`: `received` → `validated` → `rejected` → `cancelled`.
`notification`: `queued` → `sent` → `delivered` → `read` → `failed` | `opted_out`.

### Eventos
`outbox.enqueued`, `outbox.sent`, `outbox.failed`, `inbox.received`, `fiscal.validated`, `fiscal.rejected`, `notification.delivered`.

### Regras
- **Outbox transacional:** a mensagem é gravada na mesma transação do fato de negócio; publicação é assíncrona, com reprocessamento seguro e dead-letter visível em tela.
- **API versionada e idempotente:** prefixo `/api/v1`, quebra de contrato só em `/v2`; escrita aceita `Idempotency-Key` e devolve a mesma resposta para a mesma chave.
- Documentos fiscais brasileiros são **termo próprio, não traduzido** (NF-e, CT-e, MDF-e, romaneio, tara): validação de chave (44 dígitos, DV) e de situação junto ao provedor.
- ERP (SAP Business One / HANA, Odoo), MES/Opcenter, WMS, TMS, PCP, BI: cada um é um `integration_endpoint` com contrato próprio e mapeamento declarado, nunca acoplado ao domínio.
- Notificação a motorista e transportadora (WhatsApp, SMS, e-mail, app) com **opt-out** e **log de entrega** — opt-out é respeitado em qualquer canal, inclusive automático.

### Invariantes de banco
```sql
CREATE UNIQUE INDEX uq_outbox_dedup ON outbox_message(aggregate_type, aggregate_id, event_seq);
CREATE UNIQUE INDEX uq_idempotency_key ON api_request(client_id, idempotency_key);
CONSTRAINT ck_fiscal_key CHECK (kind NOT IN ('nfe','cte','mdfe') OR length(access_key) = 44)
CONSTRAINT ck_notification_optout CHECK (state <> 'sent' OR opted_out = false)
CONSTRAINT ck_outbox_retry CHECK (retry_count <= max_retry OR state = 'dead_letter')
```

### API
```
GET  /api/v1/integrations/outbox?state=       POST /api/v1/integrations/outbox/{id}/retry
POST /api/v1/fiscal/documents                 GET  /api/v1/fiscal/documents/{key}/status
POST /api/v1/notifications                    GET  /api/v1/notifications/{id}/delivery
POST /api/v1/webhooks/{endpoint}              # entrada assinada (HMAC) e idempotente
```

### Tela
`ListWorkspace` de integração: fila de outbox, dead-letter com payload e botão de reprocessar, histórico de entrega de notificação, status de documento fiscal por visita.

### KPI
Latência de publicação do outbox (p95) · taxa de dead-letter · % de documento fiscal validado na primeira tentativa · taxa de entrega de notificação por canal · nº de reprocessamentos.

---

## 3.10 Torre de controle e IA

### Entidades
`control_board_view`, `ai_proposal`, `ai_proposal_item`, `human_decision`, `forecast` (previsão de liberação), `bottleneck_signal`.

### Estados
`ai_proposal`: **`proposed`** → `under_review` → `approved` → `executing` → `executed` | `rejected` | `expired`.

### Eventos
`ai.proposal_created`, `ai.proposal_reviewed`, `ai.proposal_approved`, `ai.proposal_rejected`, `ai.proposal_executed`, `forecast.updated`, `bottleneck.detected`.

### Regras
- Painel único: fila de portaria, ocupação, atraso por doca, risco de demurrage, gargalo previsto.
- O agente propõe: resequenciamento de doca, remanejo de vaga, priorização de fila, alerta de dwell excessivo, previsão de hora de liberação. Cada proposta carrega **justificativa e impacto estimado** — proposta sem impacto calculado não vai para a tela.
- **Toda proposta nasce em `proposed` e só vira ação após aprovação humana registrada em banco. Nenhum caminho de código emite comando físico a partir de sugestão não aprovada.** Isso é interlock, não burocracia: é o que impede a torre de abrir uma cancela sozinha.
- Proposta expira (janela curta, tipicamente 10 min) — pátio muda rápido e proposta velha é ruído.
- A decisão humana (aprovar, rejeitar, editar) é dado de treino e de auditoria, com identificação do decisor.

### Invariantes de banco
```sql
CONSTRAINT ck_ai_proposal_approval CHECK (
  state NOT IN ('approved','executing','executed')
  OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
-- execução exige proposta aprovada e não expirada
CONSTRAINT ck_ai_proposal_expiry CHECK (state <> 'executing' OR expires_at > now())
-- comando físico referencia decisão humana (ver 3.8)
CONSTRAINT ck_command_ai_approval CHECK (
  origin <> 'ai' OR approved_by IS NOT NULL)
CONSTRAINT ck_ai_proposal_impact CHECK (impact_json IS NOT NULL)
```

### API
```
GET  /api/v1/control-tower/overview
GET  /api/v1/ai/proposals?state=proposed
POST /api/v1/ai/proposals/{id}/approve   # registra decisor; só aqui nasce ação
POST /api/v1/ai/proposals/{id}/reject    # exige reason_code
GET  /api/v1/ai/forecast/release-time?visit_id=
```

### Tela
`WallBoard` para sala de controle (densidade compacta, pátio inteiro sem rolar) + `OperationalConsole` com coluna de propostas: cada card mostra o que muda, o impacto e dois botões — aprovar e rejeitar. Nada executa por clique acidental: aprovação de comando físico pede confirmação explícita.

### KPI
% de propostas aprovadas · tempo de decisão · impacto realizado vs. estimado · demurrage evitada · nº de alertas de dwell excessivo tratados · erro da previsão de liberação (MAE em minutos).

---

## 3.11 Segurança, EHS e compliance

### Entidades
`person`, `access_grant`, `role`, `permission`, `audit_event` (append-only), `consent`, `retention_policy`, `emergency_roster`, `lgpd_request`.

### Estados
`consent`: `granted` → `withdrawn`. `lgpd_request`: `received` → `in_progress` → `fulfilled` → `rejected`.
`access_grant`: `active` → `suspended` → `revoked`.

### Eventos
`access.granted`, `access.revoked`, `audit.recorded`, `consent.granted`, `consent.withdrawn`, `lgpd.request_received`, `lgpd.anonymized`, `emergency.roster_generated`.

### Regras
- **LGPD:** imagem de motorista, biometria, placa e geolocalização são **dado pessoal**. Cada categoria declara base legal (execução de contrato / legítimo interesse / obrigação legal), finalidade, prazo de retenção, regra de anonimização e canal de acesso do titular.
  - Imagem de pesagem e LPR: retenção padrão 90 dias, depois anonimização (blur de rosto, retenção só do recorte da placa por 12 meses para fins fiscais). *// ASSUNÇÃO: prazos revisáveis pelo DPO da planta.*
  - Geolocalização de manobrista: retenção 30 dias, agregada depois disso.
- **Trilha imutável** de todo evento de acesso, pesagem, comando físico e decisão humana — append-only por trigger, nunca por disciplina de código.
- **Segregação de função:** quem agenda ≠ quem libera ≠ quem pesa ≠ quem aprova exceção. Perfis mínimos: `yard.scheduler`, `yard.gate`, `yard.scale`, `yard.spotter`, `yard.dock`, `yard.supervisor`, `yard.controller`, `yard.admin`, `portal.carrier`.
- **Registro de emergência:** lista de pessoas e veículos em pátio disponível **em tela e em papel** (PDF gerado sob demanda, com hora de corte), funcionando mesmo com backend degradado (cache local no dispositivo da guarita).

### Invariantes de banco
```sql
CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION yard_deny_mutation();
-- segregação de função: o aprovador não pode ser o solicitante
CONSTRAINT ck_exception_segregation CHECK (approved_by <> requested_by)
-- dado pessoal declara base legal e retenção
CONSTRAINT ck_personal_data_policy CHECK (
  NOT is_personal_data OR (legal_basis IS NOT NULL AND retention_days IS NOT NULL))
-- consentimento retirado bloqueia uso
CONSTRAINT ck_consent_withdrawn CHECK (state <> 'withdrawn' OR withdrawn_at IS NOT NULL)
```

### API
```
GET  /api/v1/security/roles              POST /api/v1/security/grants
GET  /api/v1/audit?aggregate=&from=&to=  # somente leitura, sempre
GET  /api/v1/emergency/roster            GET /api/v1/emergency/roster.pdf
POST /api/v1/lgpd/requests               POST /api/v1/lgpd/requests/{id}/fulfill
```

### Tela
Painel de auditoria com filtro por agregado e ator; tela de emergência em alto contraste, imprimível, com contagem de pessoas e veículos por zona; gestão de perfis com matriz de segregação visível (conflito de função destacado).

### KPI
% de eventos críticos com trilha completa · nº de conflitos de segregação detectados · tempo de geração da lista de emergência · nº de solicitações LGPD atendidas no prazo · % de dado pessoal dentro da política de retenção.

---

## 3.12 Indicadores — fórmula, granularidade, fonte e meta

Todos os KPIs são calculados sobre eventos (`visit_event`, `signal_reading`, `dock_stage_timing`), nunca sobre campo digitado à parte. Meta é valor de referência do cenário mínimo; cada planta parametriza a sua.

| KPI | Fórmula | Granularidade | Fonte | Meta |
|---|---|---|---|---|
| Tempo de gate-in | `gate_in_at − arrived_at` | por visita; p50/p95 por guarita/turno | `visit_event` (gate.vehicle_detected → visit.gate_in) | p95 ≤ 6 min |
| Dwell por etapa | `Σ (fim_etapa − início_etapa)` por etapa | por visita e por etapa | `visit_event` + `dock_stage_timing` | conforme `operation_type.target_dwell_minutes` |
| Dwell total | `gate_out_at − arrived_at` | por visita; média/p95 por operação | `visit` | p95 ≤ meta do tipo de operação |
| Turnaround do veículo | `gate_out_at − arrived_at` do par entrada/saída da mesma visita | por veículo/transportadora/dia | `visit` | ≤ 120 min (granel), ≤ 90 min (paletizado) |
| Utilização de doca | `Σ tempo ocupado ÷ tempo disponível no turno` | por doca/turno/dia | `dock_visit` + `shift_calendar` | 70–85 % (acima disso vira fila) |
| Aderência ao agendamento | `chegadas dentro da janela ÷ agendamentos confirmados` | por transportadora/doca/dia | `appointment` + `visit.arrived_at` | ≥ 85 % |
| Fila média e de pico | média e máx. de veículos em `at_gate_in`/`queued` por janela de 15 min | por guarita/hora | `visit` (série temporal) | pico ≤ 8 veículos |
| Movimentos por manobrista | `move_task confirmadas ÷ hora trabalhada` | por operador/turno | `move_task` | ≥ 6 /h |
| Demurrage/detenção evitada | `Σ max(0, limite_contratual − dwell_real) × tarifa` | por transportadora/mês | `visit` + `freight_contract` | tendência crescente |
| Divergência de pesagem | `|peso_líquido − peso_documento| ÷ peso_documento` | por ticket; média e % fora de tolerância | `weighing_ticket` + `fiscal_document` | ≤ 0,5 % fora de tolerância |
| Taxa de exceção manual | `eventos com source='manual' ÷ total de eventos` | por processo (gate, balança, movimentação) | `visit_event.source` | ≤ 15 % |
| Disponibilidade de dispositivo | `tempo online ÷ tempo total` por dispositivo | por dispositivo/classe/dia | `device_health` | ≥ 99 % (cancela, balança) |
| % evento automático vs. digitado | `source IN ('device','system') ÷ total` | por processo/dia | `visit_event.source` | ≥ 85 % |

---

# 2. Contratos transversais

**Erro.** A API devolve `{"error": {"code": "ERR_YARD_DOC_EXPIRED", "params": {...}}}`. Nenhum texto humano na API; o texto vive em `locales/*/errors.json`.

**Tempo.** Banco em UTC (`timestamptz`). Exibição no fuso **da planta**, não do navegador. Evento de campo carrega `occurred_at` do campo e `received_at` do servidor — os dois importam quando a rede cai.

**Unidade.** Peso em **kg** no dado; exibição configurável (kg / t / lb). Distância em metros.

**Idempotência.** Toda escrita de origem externa ou de dispositivo aceita chave idempotente (`Idempotency-Key` no HTTP, `client_event_id` no payload de campo).

**Estado de dado na UI.** Todo valor originado de sensor mostra `fresh` / `stale` / `invalid` / `no_comm`. Número sem qualificação de frescor é mentira em sala de controle.

**Interlock de IA.** `ai_proposal.state = 'proposed'` é o único ponto de entrada de sugestão. `command.origin = 'ai'` exige `approved_by`. Os dois invariantes vivem no banco.

---

# 3. Ordem de construção (fatias verticais)

| Fatia | Conteúdo | Blocos |
|---|---|---|
| 1 | Núcleo de pátio: cadastro, mapa, gate-in/out manual, dwell | 3.1 (parcial), 3.3 (manual), 3.5 |
| 2 | Agendamento, portal do transportador, reserva de vaga | 3.2, 3.1 (completo) |
| 3 | Balança: driver serial/TCP + simulador, ticket com hash | 3.4 |
| 4 | Automação de portaria: LPR, QR, RFID, checklist, cancela | 3.3 (completo) |
| 5 | Movimentação e doca | 3.6, 3.7 |
| 6 | IoT/OT, operação degradada, RTLS opcional | 3.8 |
| 7 | Torre de controle e IA com aprovação humana | 3.10 |
| 8 | Integrações ERP/MES/WMS/TMS/BI, fiscal, notificação | 3.9 |
| — | Transversal desde a Fatia 1 | 3.11, 3.12 |

Cada fatia entra em produção sozinha e entrega junto: migration, endpoints, telas, componentes de DS no Storybook, chaves de i18n nos dois locales, seed atualizado e roteiro de verificação.
