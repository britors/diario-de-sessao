# diario-de-sessao

[Português](#português) · [English](#english)

## Português

Plugin do [Claude Code](https://claude.com/claude-code) que grava um diário de cada sessão. Ao fechar a sessão, um hook escreve em Markdown o que foi feito. Na sessão seguinte, `/retomar` lê o último diário do projeto e continua de onde você parou.

### O que vai no diário

- **Pedidos** que você digitou.
- **Arquivos alterados** pelo Claude (Edit, Write, NotebookEdit), com o número de edições.
- **Commits** feitos no repositório durante a sessão.
- **Decisões** e **pendências** que o Claude anotou ao longo da sessão. As pendências incluem também as tarefas não concluídas do TodoWrite e os arquivos não commitados.
- **Última resposta** do Claude, que costuma resumir o estado do trabalho.
- **Custo** por modelo, com os subagentes, em tokens e US$, pela mesma conta do `custo_real.py` do [estimar-tokens](https://github.com/britors/estimar-tokens).

Os diários ficam em `~/.claude/diario-de-sessao/<projeto>/`, um arquivo por sessão (`AAAA-MM-DD_HHMM_<sessão>.md`), fora do seu repositório. O projeto é a raiz do repositório git, ou a pasta da sessão.

### Instalação

No Claude Code 2.1.275 ou mais novo, dentro de uma sessão:

```
/plugin install diario-de-sessao --marketplace britors/diario-de-sessao
```

Em versões anteriores:

```
/plugin marketplace add britors/diario-de-sessao
/plugin install diario-de-sessao@diario-de-sessao
```

Precisa de `python3` no PATH. `git` é opcional (commits e arquivos não commitados).

### Uso

- **Retomar:** digite `/retomar`. O Claude lê o último diário, confere o `git status` e diz o que foi feito, o que ficou pendente e o próximo passo que sugere.
- **Anotar:** no início de cada sessão, o Claude é lembrado de registrar decisões e pendências. Você também pode pedir: "anota como pendência revisar o CSS".
- **Na mão:**

  ```
  python3 skills/retomar/scripts/diario.py ultimo [--caminho]
  python3 skills/retomar/scripts/diario.py listar [--n 10]
  python3 skills/retomar/scripts/diario.py anotar decisao|pendencia "texto"
  ```

Para mudar os preços, crie `~/.claude/estimar-tokens/precos.json` no formato de `skills/retomar/references/precos.json`. É o mesmo arquivo que o estimar-tokens usa. Sessões sem nenhuma resposta do Claude não geram diário.

### Estrutura

```
.claude-plugin/plugin.json                 manifesto
.claude-plugin/marketplace.json            marketplace de um plugin só
skills/retomar/SKILL.md                    /retomar e como anotar
skills/retomar/scripts/diario.py           hooks, diário e comandos
skills/retomar/references/precos.json      preços da API por modelo
hooks/hooks.json                           SessionStart e SessionEnd
tests/test_diario.py                       testes
```

Para rodar os testes: `python3 -m unittest discover -s tests`.

## English

[Claude Code](https://claude.com/claude-code) plugin that keeps a log of every session. When a session ends, a hook writes a Markdown entry with your requests, the files Claude changed, the commits, the decisions and pending items Claude noted, Claude's last reply and the session cost per model (subagents included, same math as `custo_real.py` from [estimar-tokens](https://github.com/britors/estimar-tokens)).

Logs are stored in `~/.claude/diario-de-sessao/<project>/`, outside your repository. In the next session, `/retomar` reads the latest log for the project, checks `git status` and tells you what was done, what is pending and the suggested next step.

Install with `/plugin install diario-de-sessao --marketplace britors/diario-de-sessao`.

## Licença / License

[GPL-3.0](LICENSE)
