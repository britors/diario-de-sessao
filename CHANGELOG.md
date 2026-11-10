# Changelog

## 1.0.1 — 10/11/2026

- O diário vai para a pasta em que a sessão começou, mesmo que ela tenha feito `cd` para outro repositório. Antes, o hook `SessionEnd` usava a pasta final e gravava o diário no repositório errado.
- `anotar`, `ultimo` e `listar` também acham a pasta da sessão ativa quando rodados de uma subpasta, para as notas entrarem no diário certo.

## 1.0.0 — 10/11/2026

- Hook `SessionEnd`: grava em `~/.claude/diario-de-sessao/<projeto>/` um diário em Markdown com os pedidos, os arquivos alterados, os commits, as decisões, as pendências, a última resposta do Claude e o custo da sessão.
- Pendências automáticas: tarefas não concluídas do TodoWrite e arquivos não commitados.
- Custo por modelo, com subagentes, pela mesma lógica do `custo_real.py` do estimar-tokens.
- Hook `SessionStart`: lembra o Claude de anotar decisões e pendências e aponta o último diário.
- `scripts/diario.py anotar`, `ultimo` e `listar`.
- Skill `/retomar`: lê o último diário do projeto e continua de onde parou.
- Testes e CI.
