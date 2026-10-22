## O que muda
<!-- Resumo da mudança e o porquê. Referencie a issue: "Fecha #123". -->

## Tipo
- [ ] Correção de bug
- [ ] Nova funcionalidade
- [ ] Documentação
- [ ] Refatoração / manutenção

## Como testei
<!-- Passos, seed usado, navegadores/dispositivos (desktop, totem, celular). -->

## Capturas
<!-- Se mexeu na interface, antes/depois — só com o seed de demonstração. -->

## Checklist
- [ ] `pytest`, `npm run i18n:check`, `typecheck` e `lint` sem erro (e nenhum aviso novo do `ruff`)
- [ ] Invariante nova está no banco e tem teste que tenta violá-la
- [ ] Migration nova (nenhuma migration existente foi editada)
- [ ] Textos novos nos dois locales (pt-BR e en-US)
- [ ] Sem segredos, `.env`, dumps ou dados reais (placas, motoristas, transportadoras) no commit
