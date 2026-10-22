# GPlanSiS|YARD — Guia de uso

Panorama completo do sistema: o que cada tela faz, em que ordem se usa, e o que o sistema
**não deixa** fazer. Escrito para quem opera o pátio (portaria, balança, manobra, doca,
supervisão) e para quem acompanha a operação de fora dela.

O fio condutor é uma visita real de ponta a ponta — a placa **AAA3251**, motorista
**Stéfano Motorista** — a mesma que o roteiro automatizado executa a cada verificação.

---

## 1. Antes de começar

### Subir o sistema

```bash
docker compose up -d                 # Postgres/TimescaleDB, API, web
cd apps/api && alembic upgrade head  # esquema e invariantes
python -m app.seed                   # 1 planta, 3 guaritas, 2 balanças, 24 docas, 180 vagas
```

A web sobe em `http://localhost:5173`, a API em `http://localhost:8088`
(`/docs` para o contrato OpenAPI, `/health` e `/ready` para monitoração).

O banco já nasce cheio: **nenhuma tela abre vazia**. O simulador de campo
(`python -m app.simulator`) mantém o pátio em movimento — cancelas, balanças, leitores
LPR e posições — para que dê para treinar e demonstrar sem caminhão nenhum.

### A barra superior, presente em todas as telas

| Controle | Para que serve |
|---|---|
| **Idioma** | pt-BR / en-US. Troca em tempo real, sem recarregar. |
| **Tema** | Claro, escuro e **HMI** (alto contraste, para sala de controle). |
| **Densidade** | Compacta, padrão e **toque** (alvos de 44 px, para totem e tablet de pátio). |
| **Indicador ao vivo** | Verde: a tela está recebendo atualização do campo. Cinza: está lendo cache. |

A paleta segue ISA-101: **cor só aparece onde há anormalidade**. Uma tela toda cinza é
uma operação saudável — não é uma tela apagada.

### Quem pode o quê

A segregação de função é do sistema, não do combinado: quem agenda não libera, quem abre
uma pendência não a libera, e uma sugestão de IA não vira comando físico sem aprovação
humana registrada.

| Perfil | Faz |
|---|---|
| `yard.scheduler` | Cria, confirma, reprograma e cancela janelas. |
| `yard.gate` | Identificação, triagem, checklist, gate-in e gate-out. |
| `yard.scale` | Abre ticket, captura bruto e tara, fecha ticket. |
| `yard.spotter` | Aceita, inicia e confirma manobras. |
| `yard.dock` | Cronometria de doca e registro de divergência. |
| `yard.supervisor` | Libera pendências, aprova exceções e comandos de IA. |
| `yard.controller` | Torre de controle, KPIs, alarmes (leitura ampla). |
| `portal.carrier` | Portal do transportador: pede janela, acompanha a própria frota. |

---

## 2. O passo a passo de uma visita

### Passo 1 — Agendamento (`/scheduling`)

A tela tem três partes: o **gráfico de janelas** (Gantt por doca), o **formulário de nova
janela** e a **lista de agendamentos** com o histórico de cada um.

1. Clique em um espaço vazio na faixa da doca desejada — a janela já abre com doca e
   horário preenchidos. (Também dá para abrir pelo botão de nova janela e escolher tudo
   à mão.)
2. Informe placa, motorista, tipo de operação e a duração. O sistema mostra a **grade de
   disponibilidade**: onde cabe, onde não cabe e por quê.
3. Salve. A janela nasce em `requested`.
4. **Confirme** a janela. É a confirmação que **reserva a vaga** no pátio (aqui, a `A-02`)
   e trava a capacidade do recurso.

O que o gráfico mostra:

- **faixa colorida** = janela agendada naquela doca;
- **hachura** = doca *bloqueada* no dia (manutenção, parada de planta) — e só isso;
- **linha vertical** = agora;
- janela que começou antes do início do gráfico aparece **aparada na borda**, com marca de
  continuação, em vez de vazar para a doca de cima.

> Uma doca *ocupada agora* continua agendável para mais tarde. Ocupação é estado do
> momento; bloqueio é estado do dia. O gráfico não mistura os dois.

**Clique na faixa** e abre o detalhe da janela: estado, horário, prioridade, canal, vaga
reservada, rastro de mudanças e as ações (confirmar, trocar de doca, marcar não
comparecimento, cancelar). **Arraste** a faixa para reprogramar; clicar só abre.

O sistema recusa, com mensagem específica: duas janelas sobrepostas na mesma doca;
capacidade de recurso estourada (empilhadeira, equipe); janela dentro de parada de planta;
e **edição em cima de versão velha** (`ERR_YARD_APPOINTMENT_STALE`) — se alguém mexeu no
agendamento enquanto você o tinha aberto, sua alteração não sobrescreve a dele em silêncio.

Reprogramar e cancelar **exigem motivo**, e o impacto da mudança (quem mais foi empurrado)
aparece antes de você confirmar. Tudo fica no histórico da janela.

### Passo 2 — Chegada e identificação (`/kiosk`, totem da guarita)

O totem é o fluxo em etapas, feito para dedo e luva: passos grandes, um por vez, com o
trilho de passos no topo permitindo voltar ao que já foi concluído.

1. **Identificar**: LPR (leitura de placa), QR do agendamento, ou manual.
   A leitura vem com **confiança**. Abaixo do limite (0,85), o sistema **não libera** —
   `ERR_YARD_IDENTIFICATION_LOW_CONFIDENCE` — e pede confirmação humana. Placa borrada de
   madrugada não vira entrada automática.
2. **Triagem**: o sistema cruza a identificação com agendamento, validade de CNH, restrição
   do veículo e pendências da transportadora, e responde `admit`, `hold` ou `reject`.
3. **Gate-in**: registra a entrada. A visita nasce (`YRD-...`) no estado `at_gate_in`.
4. **Checklist de entrada**: os itens exigidos vêm do tipo de operação. Item **bloqueante**
   reprovado (EPI, lacre, documento) **segura o veículo na guarita** — a liberação para o
   pátio é recusada com `ERR_YARD_CHECKLIST_FAILED` listando os itens.
   A **reinspeção** é o caminho de volta: corrigido o problema, reinspeciona e segue.
5. **Cancela**: o comando só sai se o **permissivo do CLP** estiver em `true` e com
   qualidade `good`. Leitura velha (`stale`) não abre cancela.

### Passo 3 — Console da guarita (`/gate`)

A visão do fiscal de portaria, com teclado: fila de chegada, check-in manual completo
(placa, documento do motorista, tipo de operação, produto, nota, lacre), a lista de quem
está no pátio e a ação de **gate-out**. Serve de retaguarda ao totem — e de plano B quando
o totem cai.

### Passo 4 — Pátio e vaga (`/`, Torre de Controle)

A tela inicial é o **mapa do pátio** mais a fila de veículos e os KPIs do turno.

- O mapa se ajusta sozinho ao conteúdo; há **zoom, pan e "ajustar à tela"**. A placa é
  desenhada dentro da vaga, no tamanho que couber, e some quando não couber — sem texto
  atravessando o desenho.
- Legenda: livre, ocupada, bloqueada e **acima do tempo-alvo**.
- **Clique em qualquer vaga, doca ou linha da fila** e abre o detalhe da visita: dados,
  tempos, eventos, tickets de pesagem e as ações disponíveis dali (manobrar, encostar em
  doca, pesar, dar saída).
- **Clique em um KPI** e ele abre: como a conta é feita, as contagens vizinhas e a lista
  nominal dos veículos por trás do número — e dessa lista se abre a visita.

A alocação de vaga respeita a reserva do agendamento: quem confirmou a `A-02` recebe a
`A-02`. A alocação automática (de quem chega sem janela) **pula as vagas reservadas** —
reserva que qualquer um ocupa não é reserva.

KPIs do topo: veículos no pátio, em guarita, em doca, ocupação de vagas e de docas, **dwell
p95**, veículos acima do tempo-alvo e o **percentual de eventos automáticos** (quanto da
operação o sistema captura sozinho, sem digitação).

### Passo 5 — Manobra (`/moves`)

A fila do manobrista, **ordenada por custo, não por ordem de chegada**: distância, conflito
de rota e urgência entram na conta.

1. **Aceitar** a tarefa (ela passa a ser sua).
2. **Iniciar**.
3. **Confirmar** — e aqui está o ponto: a confirmação normal é por **leitura do QR da
   vaga**. Ler o QR errado não vira erro de digitação, vira **desvio registrado**
   (`ERR_YARD_MOVE_WRONG_SLOT`, com esperado × lido).
   A confirmação **manual exige motivo**, e o banco recusa confirmação manual sem
   justificativa mesmo por SQL direto.

Um veículo tem **uma** manobra ativa. Evento offline reenviado não duplica tarefa. Manobra
em andamento pode ser cancelada — o pátio muda no meio do caminho.

### Passo 6 — Doca

Encostou, o relógio corre por etapa: **chegada → encosto → início → pausa → retomada →
fim → liberação**. A ordem é obrigatória (`ERR_YARD_DOCK_STAGE_INVALID`); pausa pede
motivo (falta de empilhadeira, refeição, aguardando conferência) — é isso que transforma
"demorou 3 h" em "1 h 40 esperando empilhadeira".

A doca recebe **um** veículo por vez, garantido por restrição de banco, não por disciplina.
A ocupação se fecha na liberação **e também na saída do pátio** — veículo que vai embora
não deixa a doca presa.

Divergência de carga (quantidade, avaria, lacre) **exige evidência fotográfica** e abre
pendência automaticamente.

### Passo 7 — Balança (`/weighing`)

1. **Abrir ticket**: escolha a balança e a visita (a busca aceita placa ou referência).
2. **Capturar bruto**: o peso vem da balança. O sistema checa o **posicionamento** do
   veículo — mal posicionado não pesa (`ERR_YARD_WEIGHT_VEHICLE_MISPLACED`).
3. **Capturar tara**: aferida na hora; a tara cadastral serve de referência, não de verdade.
4. O **líquido** e a **divergência contra a nota** são calculados e mostrados na hora, com
   a tolerância do produto.
5. **Fechar o ticket**. Ele ganha um **hash de integridade** e vira imutável
   (`ERR_YARD_TICKET_IMMUTABLE`) — correção se faz com **nova pesagem**, não com edição.

Peso digitado à mão exige **motivo e segundo fator** (outra pessoa). Divergência acima da
tolerância **abre pendência** e segura a saída — com caminho auditado de liberação, não
com um veículo preso sem explicação.

Da tela de detalhe da visita, o botão de pesagem já abre a balança com o ticket carregado.

### Passo 8 — Saída (`/gate` ou detalhe da visita)

O gate-out confere, nesta ordem: pendências abertas, checklist de saída, pesagem exigida
pela operação e documento fiscal. Bloqueou, a tela diz **qual** é a pendência
(`ERR_YARD_EXIT_BLOCKED_BY_PENDENCY` com o motivo).

Para liberar, **outra pessoa**: quem abriu a pendência não a libera
(`ERR_YARD_HOLD_SEGREGATION`). Liberada, o gate-out registra a saída, libera vaga e doca e
fecha o dwell.

### Passo 9 — Trilha (`/visits`)

A lista de visitas com busca por placa, motorista, transportadora ou referência, filtro de
"somente abertas" e o detalhe completo. A trilha de eventos mostra **o que aconteceu, quando,
por qual fonte** (dispositivo, manual, integração) e a transição de estado de cada evento.
A trilha é **append-only**: o banco recusa alteração e exclusão de evento.

Cada marco também sai para ERP/WMS/BI pela caixa de saída transacional — com idempotência,
reentrega e registro do que foi entregue.

---

## 3. Torre de controle e IA (`/tower`)

A tela de quem olha o pátio inteiro:

- **KPIs de risco**: fila de guarita, veículos acima do dwell, pendências abertas, manobras
  em aberto, agendamentos atrasados e **risco de demurrage**.
- **Alarmes** por prioridade ISA-18.2, com reconhecimento nominal e registro de quem
  reconheceu.
- **Propostas da IA**: cada sugestão vem com **confiança**, janela de validade e o
  intertravamento que precisa estar satisfeito.

O ponto inegociável: **ação de IA nasce como sugestão**. O ciclo é
`gerar → aprovar (ou rejeitar / engavetar) → executar`, com nome e horário em cada etapa.
Tentar executar sem aprovação é recusado pelo banco — `ERR_YARD_COMMAND_AI_NOT_APPROVED`
— e não pela boa vontade da tela. Nenhum comando físico (cancela, semáforo, chamada de
doca) sai por decisão automática.

---

## 4. Como o sistema fala com você

Erro aqui não é texto solto: o backend devolve **código + parâmetros** e a tela traduz.
Os mesmos códigos aparecem no log, no teste e na tela — o que o operador lê é o que o
suporte procura.

| Código | O que aconteceu | O que fazer |
|---|---|---|
| `ERR_YARD_IDENTIFICATION_LOW_CONFIDENCE` | Leitura abaixo do limite | Confirmar a placa manualmente |
| `ERR_YARD_CHECKLIST_FAILED` | Item bloqueante reprovado | Corrigir e reinspecionar |
| `ERR_YARD_APPOINTMENT_STALE` | Alguém alterou a janela antes | Recarregar e refazer a alteração |
| `ERR_YARD_SLOT_OCCUPIED` / `ERR_YARD_SLOT_BLOCKED` | Vaga ocupada ou bloqueada | Escolher outra ou liberar a vaga |
| `ERR_YARD_MOVE_WRONG_SLOT` | QR lido ≠ vaga esperada | Conferir a vaga; fica registrado como desvio |
| `ERR_YARD_MOVE_CONFIRMATION_REQUIRED` | Confirmação manual sem motivo | Informar a justificativa |
| `ERR_YARD_DOCK_STAGE_INVALID` | Etapa fora de ordem | Seguir a sequência da doca |
| `ERR_YARD_WEIGHT_VEHICLE_MISPLACED` | Veículo mal posicionado | Reposicionar e repetir a captura |
| `ERR_YARD_TICKET_IMMUTABLE` | Ticket fechado | Abrir nova pesagem |
| `ERR_YARD_EXIT_BLOCKED_BY_PENDENCY` | Pendência aberta | Resolver e pedir liberação |
| `ERR_YARD_HOLD_SEGREGATION` | Quem abriu tentou liberar | Outra pessoa libera |
| `ERR_YARD_COMMAND_AI_NOT_APPROVED` | Execução sem aprovação | Aprovar antes de executar |

Datas, horas, números e pesos seguem o idioma escolhido. O banco guarda **UTC**; a tela
mostra no **fuso da planta** — turno que vira meia-noite não vira relatório errado.

---

## 5. O que o sistema garante, mesmo contra o sistema

Estas regras vivem no **banco** (CHECK, EXCLUDE, trigger). Valem para a tela, para a API,
para a integração e para o SQL digitado à mão às duas da manhã:

- duas janelas não se sobrepõem na mesma doca;
- duas visitas não ocupam a mesma vaga ao mesmo tempo, nem a mesma doca;
- confirmação manual de manobra sem motivo não entra;
- evento de trilha não se altera nem se apaga;
- ticket de pesagem fechado não muda;
- visita com pendência aberta não sai;
- comando de IA não executado sem aprovação registrada.

Cada uma tem um teste que **tenta violá-la por SQL direto** e exige que o banco recuse.

---

## 6. Verificação de ponta a ponta

O roteiro que percorre as 12 etapas deste guia, com a placa do exemplo:

```bash
cd apps/api
python scripts/e2e_demo.py --api http://127.0.0.1:8088 \
       --plate AAA3251 --driver "Stéfano Motorista"
```

Ele não testa só o caminho feliz: em cada etapa **tenta violar a regra** e exige a recusa
certa (versão velha, checklist reprovado, QR errado, ticket fechado, saída bloqueada,
IA sem aprovação). Pode rodar quantas vezes quiser — ele mesmo limpa o que deixou para trás.

Saída esperada ao final:

```
✓ fluxo completo: 12 etapas, nenhuma regra violada.
```

Demais verificações:

```bash
cd apps/api && python -m pytest -q          # 80 testes, banco real
cd apps/web && node scripts/i18n-check.mjs  # nenhuma chave faltando, nenhum literal em JSX
cd apps/web && node scripts/responsive-check.mjs  # 4 aparelhos × 8 telas
cd apps/web && node scripts/smoke-ui.mjs    # interações reais nas telas principais
```

---

## 7. Em uma frase

Cada tela deste guia existe para transformar uma decisão de pátio em **registro**: quem
decidiu, quando, com base em quê — e o que o sistema recusou fazer no caminho.
