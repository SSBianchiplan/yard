# Política de segurança

## Versões suportadas
| Versão | Suporte |
|---|---|
| 0.1.x / `main` (em yard.gplansis.com) | ✅ |

## Como relatar uma vulnerabilidade
**Não abra issue pública.** Envie um e-mail para **contato@gplansis.com** com o assunto `[SEGURANÇA] GPlanSiS|YARD`, contendo:
- descrição do problema e impacto;
- passos para reproduzir (ou prova de conceito);
- versão, navegador e ambiente usados.

Confirmamos o recebimento assim que possível, mantemos você informado sobre a correção e damos crédito na publicação, se desejar.

## Escopo
Autenticação (login local e OIDC), sessão e bloqueio, perfis por rota, portal do transportador, comandos de campo (cancela, permissivos, segundo fator da balança), aprovação de propostas de IA, webhooks e idempotência das integrações, WebSocket/SSE e cabeçalhos/CSP. Testes devem ser feitos numa instância local — **não** teste contra yard.gplansis.com nem acesse dados de outras pessoas.
