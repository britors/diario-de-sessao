---
name: retomar
description: Esta skill deve ser usada quando o usuário digitar /retomar ou pedir para "retomar", "continuar de onde parei", "o que fizemos na última sessão", "o que ficou pendente" ou "ler o diário", e quando uma decisão relevante for tomada ou algo ficar para depois, para anotá-la no diário. This skill should be used when the user types /retomar or asks to "resume", "continue where I left off", "what did we do last session", "what is pending" or "read the session log", and when a relevant decision is made or something is left for later, to note it in the log.
---

# Retomar

Ao fim de cada sessão, o hook do diario-de-sessao grava um diário em Markdown com os pedidos, os arquivos alterados, os commits, as decisões, as pendências, a última resposta do Claude e o custo.

O script fica em `scripts/diario.py`, ao lado deste SKILL.md. Use o caminho absoluto e rode-o na pasta do projeto.

## Retomar o trabalho

1. Leia o último diário do projeto:

   ```
   python3 <pasta desta skill>/scripts/diario.py ultimo
   ```

   Se não houver diário, diga isso ao usuário e pergunte por onde começar.

2. Confira o estado atual antes de agir: `git status --short` e `git log --oneline -5`. O que o diário diz pode ter mudado depois da sessão.
3. Responda ao usuário em poucas linhas:
   - o que foi feito na última sessão;
   - as pendências e as decisões que ainda valem;
   - o próximo passo que você sugere.
4. Espere o usuário confirmar antes de continuar o trabalho.

Para ver sessões mais antigas: `diario.py listar [--n 10]` e leia o arquivo escolhido.

## Anotar durante a sessão

Decisões e pendências não podem ser deduzidas da transcrição. Registre-as quando acontecerem, numa frase curta:

```
python3 <pasta desta skill>/scripts/diario.py anotar decisao "Usar SQLite em vez de Postgres: o app roda offline"
python3 <pasta desta skill>/scripts/diario.py anotar pendencia "Falta testar a importação de CSV com acentos"
```

- **Decisão:** uma escolha que a próxima sessão precisa respeitar, com o motivo.
- **Pendência:** algo pedido ou necessário que ficou para depois.
- Não anote o que já aparece sozinho no diário: arquivos alterados, commits, tarefas do TodoWrite e arquivos não commitados.
