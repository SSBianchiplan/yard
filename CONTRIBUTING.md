# Como contribuir com o GPlanSiS|YARD

Obrigado pelo interesse! Este guia explica como propor mudanças de forma que a revisão seja rápida.

## Antes de começar
- Leia o [código de conduta](CODE_OF_CONDUCT.md).
- Para mudanças maiores que uma correção pontual, **abra uma issue primeiro** (modelos "Ideia" ou "Bug") e combine a abordagem.
- Falhas de segurança **não** vão em issue pública: siga a [política de segurança](SECURITY.md).
- Para entender o produto: [guia de uso](docs/GUIA-DE-USO.md), [especificação](docs/SPEC-PRODUTO.md) e [assunções](ASSUNCOES.md).

## Ambiente de desenvolvimento
Siga a seção **Como rodar localmente** do [README](README.md): banco (`docker compose up -d db`), API com seeds de demonstração e front com `npm run dev`.

## Organização do código
- `apps/api/app/modules/<módulo>/` — cada módulo vertical tem `models.py`, `schemas.py`, `service.py` (regras) e `router.py` (HTTP).
- `apps/api/alembic/versions/` — migrations; cada uma lista no cabeçalho os invariantes que cria.
- `apps/web/src/pages/` — telas; `src/locales/` — textos (pt-BR e en-US); `src/lib/` — cliente da API, auth, tempo real.
- `packages/ds/` — design system (tokens, primitivos e blocos industriais) com Storybook.

## Regras do projeto
- **Nenhuma string literal em componente.** Todo texto vai para `src/locales/*/*.json`; `npm run i18n:check` quebra o build com chave faltando ou literal em JSX.
- **A API não fala idioma.** Erro é `{"error":{"code":"ERR_YARD_…","params":{…}}}`; a tradução fica no front (`errors.json`).
- **Invariante no banco.** Regra que não pode ser quebrada vira constraint, `EXCLUDE` ou trigger — e ganha um teste que tenta violá-la por SQL cru.
- **Migration só anda para frente.** Schema evolui aditivo; migration aplicada não se edita — crie outra.
- **A IA propõe, o humano decide.** Nenhum caminho de código pode executar proposta ou comando de IA sem aprovação humana registrada.
- **Qualidade do dado é dado.** Sinal de campo sempre carrega qualidade; dado obsoleto não libera ação física.
- **Cor é anormalidade** (ISA-101): use os tokens do design system, não cores soltas.
- Nunca inclua segredos, `.env`, dumps de banco ou **dados reais** (placas, motoristas, transportadoras, clientes) em commits, testes ou capturas — use o seed de demonstração.

## Antes de abrir o PR
```bash
cd apps/api && python -m pytest -q     # o ruff check . ainda acusa pendências antigas: não acrescente novas
cd ../.. && npm run i18n:check && npm run typecheck && npm run lint
```

## Pull requests
1. Faça um fork e crie uma branch a partir de `main` (`feat/…`, `fix/…`, `docs/…`).
2. Commits pequenos, com mensagem no imperativo explicando o porquê.
3. Preencha o modelo do PR: o que mudou, como testou, capturas se mexer na interface.

## Dúvidas
Abra uma issue com o modelo "Pergunta" ou escreva para contato@gplansis.com.
