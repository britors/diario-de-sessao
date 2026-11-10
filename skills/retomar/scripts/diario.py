#!/usr/bin/env python3
"""Diário de sessão do Claude Code: grava ao fim de cada sessão o que foi feito e lê o último para retomar.

    diario.py gravar                         # SessionEnd (lê o JSON do Claude Code na entrada padrão)
    diario.py lembrete                       # SessionStart (lembra de anotar e aponta o último diário)
    diario.py anotar decisao|pendencia "texto"
    diario.py ultimo [--caminho]             # mostra o último diário do projeto
    diario.py listar [--n 10]                # lista os diários do projeto

Os diários ficam em ~/.claude/diario-de-sessao/<projeto>/, um arquivo Markdown por sessão.
O custo usa a tabela em references/precos.json, sobrescrita por ~/.claude/estimar-tokens/precos.json se existir.
"""

import argparse
import collections
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
HOME = Path.home()
PASTA = HOME / ".claude" / "diario-de-sessao"
PROJETOS = HOME / ".claude" / "projects"
PRECOS_USUARIO = HOME / ".claude" / "estimar-tokens" / "precos.json"
FERRAMENTAS_DE_EDICAO = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TIPOS_NOTA = {"decisao": "Decisões", "pendencia": "Pendências"}
MAX_PEDIDOS = 10
MAX_PEDIDO = 300
MAX_RESUMO = 2000
AVISO_USD = (
    "Valores em US$ pelo preço da API Anthropic. Para assinantes do Claude.ai, "
    "é o equivalente em API, não uma cobrança."
)


# Projeto e pastas

def git(cwd, *args):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def raiz(cwd):
    """Raiz do repositório git, ou a própria pasta."""
    topo = git(cwd, "rev-parse", "--show-toplevel")
    return Path(topo.strip()) if topo else Path(cwd).resolve()


def codificar(caminho):
    return re.sub(r"[^A-Za-z0-9]", "-", str(caminho))


def cwd_inicial(transcricao, padrao):
    """Pasta em que a sessão começou: o primeiro cwd do transcript. O cwd do hook segue os `cd` da sessão."""
    for d in ler_jsonl(transcricao):
        if d.get("cwd"):
            return d["cwd"]
    return padrao


def cwd_da_sessao(cwd):
    """Pasta em que a sessão ativa começou, para anotar, ultimo e listar rodados de uma subpasta após `cd`.

    Procura em ~/.claude/projects a pasta atual e as de cima; vence a que tem o transcript mais recente.
    """
    cwd = Path(cwd).resolve()
    melhor = None
    for pasta in (cwd, *cwd.parents):
        for t in (PROJETOS / codificar(pasta)).glob("*.jsonl"):
            mt = t.stat().st_mtime
            if melhor is None or mt > melhor[0]:
                melhor = (mt, pasta)
    return melhor[1] if melhor else cwd


def pasta_projeto(cwd):
    return PASTA / codificar(raiz(cwd))


def diarios(cwd):
    pasta = pasta_projeto(cwd)
    return sorted(pasta.glob("*.md")) if pasta.is_dir() else []


# Custo (mesma lógica do custo_real.py do estimar-tokens)

def carregar_precos():
    precos = json.loads((AQUI.parent / "references" / "precos.json").read_text(encoding="utf-8"))
    try:
        outro = json.loads(PRECOS_USUARIO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return precos
    precos["modelos"].update(outro.get("modelos", {}))
    for k in ("multiplicador_escrita_5m", "multiplicador_escrita_1h"):
        precos[k] = outro.get(k, precos[k])
    return precos


def preco_modelo(precos, modelo):
    """Preço do modelo; aceita IDs com sufixo de data (claude-haiku-4-5-20251001)."""
    tabela = precos["modelos"]
    if modelo in tabela:
        return tabela[modelo]
    candidatos = [m for m in tabela if modelo and modelo.startswith(m)]
    return tabela[max(candidatos, key=len)] if candidatos else None


def custo_usd(precos, modelo, c):
    p = preco_modelo(precos, modelo)
    if p is None:
        return None
    return (
        c["entrada"] * p["entrada"]
        + c["escrita_5m"] * p["entrada"] * precos["multiplicador_escrita_5m"]
        + c["escrita_1h"] * p["entrada"] * precos["multiplicador_escrita_1h"]
        + c["leitura"] * p["leitura_cache"]
        + c["saida"] * p["saida"]
    ) / 1_000_000


def uso_detalhado(uso):
    """Separa o usage de uma resposta em entrada, escritas 5m/1h, leitura e saída."""
    cc = uso.get("cache_creation") or {}
    e5 = cc.get("ephemeral_5m_input_tokens")
    e1 = cc.get("ephemeral_1h_input_tokens")
    if e5 is None and e1 is None:
        e5, e1 = uso.get("cache_creation_input_tokens", 0) or 0, 0
    return {
        "entrada": uso.get("input_tokens", 0) or 0,
        "escrita_5m": e5 or 0,
        "escrita_1h": e1 or 0,
        "leitura": uso.get("cache_read_input_tokens", 0) or 0,
        "saida": uso.get("output_tokens", 0) or 0,
    }


def ler_jsonl(arquivo):
    try:
        with open(arquivo, encoding="utf-8", errors="replace") as f:
            for linha in f:
                try:
                    yield json.loads(linha)
                except ValueError:
                    continue
    except OSError:
        return


def somar_custo(arquivos):
    """Uso por modelo, sem duplicar pedaços da mesma mensagem."""
    por_modelo = collections.defaultdict(collections.Counter)
    for arq in arquivos:
        por_id = {}
        for d in ler_jsonl(arq):
            m = d.get("message") or {}
            if d.get("type") == "assistant" and m.get("usage") and m.get("id") and m.get("model") != "<synthetic>":
                por_id[m["id"]] = (m.get("model"), m["usage"])
        for modelo, uso in por_id.values():
            por_modelo[modelo].update(uso_detalhado(uso))
            por_modelo[modelo]["chamadas"] += 1
    return por_modelo


def usd(v):
    return "—" if v is None else f"US$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mil(n):
    return f"{n / 1000:,.1f} mil".replace(",", "X").replace(".", ",").replace("X", ".")


def tabela_custo(grupos):
    precos = carregar_precos()
    linhas = [
        "| Origem | Modelo | Chamadas | Entrada | Escrita cache | Leitura cache | Saída | Custo |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    total, total_usd, sem_preco = collections.Counter(), 0.0, set()
    for nome, por_modelo in grupos:
        for modelo, c in sorted(por_modelo.items(), key=lambda kv: -kv[1]["chamadas"]):
            valor = custo_usd(precos, modelo, c)
            if valor is None:
                sem_preco.add(modelo)
            else:
                total_usd += valor
            total.update(c)
            linhas.append(
                f"| {nome} | `{modelo}` | {c['chamadas']} | {mil(c['entrada'])} | "
                f"{mil(c['escrita_5m'] + c['escrita_1h'])} | {mil(c['leitura'])} | {mil(c['saida'])} | {usd(valor)} |"
            )
    if not total["chamadas"]:
        return [], 0.0
    linhas += [
        f"| **Total** | | **{total['chamadas']}** | **{mil(total['entrada'])}** | "
        f"**{mil(total['escrita_5m'] + total['escrita_1h'])}** | **{mil(total['leitura'])}** | "
        f"**{mil(total['saida'])}** | **{usd(total_usd)}** |",
        "",
        AVISO_USD,
    ]
    if sem_preco:
        linhas += ["", "Sem preço na tabela (fora do total): " + ", ".join(f"`{m}`" for m in sorted(sem_preco)) + "."]
    return linhas, total_usd


# Leitura da transcrição

def texto_do_usuario(m):
    """Texto digitado pelo usuário, ignorando resultados de ferramenta e mensagens do sistema."""
    conteudo = m.get("content")
    if isinstance(conteudo, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in conteudo):
            return ""
        conteudo = " ".join(b.get("text", "") for b in conteudo if isinstance(b, dict) and b.get("type") == "text")
    texto = (conteudo or "").strip() if isinstance(conteudo, str) else ""
    return "" if texto.startswith("<") else texto


def ler_sessao(transcricao):
    s = {"inicio": None, "fim": None, "pedidos": [], "arquivos": collections.Counter(), "todos": [], "resumo": ""}
    for d in ler_jsonl(transcricao):
        ts = d.get("timestamp")
        if ts:
            s["inicio"] = s["inicio"] or ts
            s["fim"] = ts
        m = d.get("message") or {}
        if d.get("type") == "user" and not d.get("isMeta"):
            texto = texto_do_usuario(m)
            if texto:
                s["pedidos"].append(texto)
        elif d.get("type") == "assistant" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if b.get("type") == "text" and b.get("text", "").strip():
                    s["resumo"] = b["text"].strip()
                elif b.get("type") == "tool_use":
                    entrada = b.get("input") or {}
                    if b.get("name") in FERRAMENTAS_DE_EDICAO:
                        caminho = entrada.get("file_path") or entrada.get("notebook_path")
                        if caminho:
                            s["arquivos"][caminho] += 1
                    elif b.get("name") == "TodoWrite":
                        s["todos"] = entrada.get("todos") or []
    return s


def hora_local(ts, formato="%d/%m/%Y %H:%M"):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime(formato)
    except (AttributeError, ValueError):
        return "?"


def encurtar(texto, n):
    texto = " ".join(texto.split())
    return texto if len(texto) <= n else texto[: n - 1] + "…"


# Notas de decisões e pendências

def arquivo_notas(cwd):
    return pasta_projeto(cwd) / "notas.jsonl"


def anotar(cwd, tipo, texto):
    arq = arquivo_notas(cwd)
    arq.parent.mkdir(parents=True, exist_ok=True)
    with open(arq, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tipo": tipo, "texto": texto, "ts": time.time()}, ensure_ascii=False) + "\n")


def consumir_notas(cwd):
    arq = arquivo_notas(cwd)
    notas = [n for n in ler_jsonl(arq) if n.get("tipo") in TIPOS_NOTA and n.get("texto")]
    arq.unlink(missing_ok=True)
    return notas


# Diário

def montar(sid, cwd, transcricao, motivo=""):
    s = ler_sessao(transcricao)
    subagentes = sorted(transcricao.parent.glob(f"{sid}/subagents/*.jsonl"))
    grupos = [("Conversa principal", somar_custo([transcricao]))]
    if subagentes:
        grupos.append((f"Subagentes ({len(subagentes)})", somar_custo(subagentes)))
    custo, total_usd = tabela_custo(grupos)
    if not custo:
        return None

    topo = raiz(cwd)
    commits = []
    if s["inicio"]:
        saida = git(topo, "log", f"--since={s['inicio']}", "--format=%h %s")
        commits = [c for c in (saida or "").splitlines() if c.strip()]
    status = git(topo, "status", "--porcelain")
    nao_commitados = [l[3:] for l in (status or "").splitlines() if l.strip()]
    notas = consumir_notas(cwd)

    def relativo(caminho):
        try:
            return str(Path(caminho).resolve().relative_to(topo))
        except ValueError:
            return caminho

    linhas = [
        f"# Diário de sessão — {topo.name} — {hora_local(s['inicio'])}",
        "",
        f"- Projeto: `{topo}`",
        f"- Sessão: `{sid}`",
        f"- Período: {hora_local(s['inicio'])} a {hora_local(s['fim'], '%H:%M')}",
        f"- Custo: {usd(total_usd)}",
    ]
    if motivo:
        linhas.append(f"- Encerramento: {motivo}")

    linhas += ["", "## Pedidos", ""]
    pedidos = s["pedidos"][:MAX_PEDIDOS]
    linhas += [f"- {encurtar(p, MAX_PEDIDO)}" for p in pedidos] or ["Nenhum."]
    if len(s["pedidos"]) > MAX_PEDIDOS:
        linhas.append(f"- … e mais {len(s['pedidos']) - MAX_PEDIDOS}.")

    linhas += ["", "## Arquivos alterados", ""]
    linhas += [
        f"- `{relativo(a)}`" + (f" ({n} edições)" if n > 1 else "")
        for a, n in sorted(s["arquivos"].items(), key=lambda kv: relativo(kv[0]))
    ] or ["Nenhum pelo Claude (alterações feitas pelo Bash não aparecem aqui)."]

    linhas += ["", "## Commits", ""]
    linhas += [f"- `{c.split(' ', 1)[0]}` {c.split(' ', 1)[1] if ' ' in c else ''}".rstrip() for c in commits] or ["Nenhum."]

    for tipo, titulo in TIPOS_NOTA.items():
        itens = [f"- {n['texto']}" for n in notas if n["tipo"] == tipo]
        if tipo == "pendencia":
            itens += [f"- {t.get('content', '')} ({t.get('status')})" for t in s["todos"] if t.get("status") != "completed"]
            if nao_commitados:
                itens.append(f"- {len(nao_commitados)} arquivo(s) não commitado(s): " + ", ".join(f"`{a}`" for a in nao_commitados[:10]))
        linhas += ["", f"## {titulo}", ""] + (itens or ["Nenhuma registrada."])

    if s["resumo"]:
        linhas += ["", "## Última resposta do Claude", ""] + [f"> {l}" if l else ">" for l in encurtar_linhas(s["resumo"])]

    linhas += ["", "## Custo", ""] + custo
    return "\n".join(linhas) + "\n", s["inicio"]


def encurtar_linhas(texto):
    if len(texto) > MAX_RESUMO:
        texto = texto[: MAX_RESUMO - 1] + "…"
    return texto.splitlines()


def gravar(dados):
    sid = dados.get("session_id")
    transcricao = Path(dados.get("transcript_path") or "")
    if not sid or not transcricao.is_file():
        return None
    cwd = cwd_inicial(transcricao, dados.get("cwd") or ".")
    resultado = montar(sid, cwd, transcricao, dados.get("reason", ""))
    if not resultado:
        return None
    texto, inicio = resultado
    pasta = pasta_projeto(cwd)
    pasta.mkdir(parents=True, exist_ok=True)
    data = hora_local(inicio, "%Y-%m-%d_%H%M") if inicio else time.strftime("%Y-%m-%d_%H%M")
    destino = pasta / f"{data}_{sid[:8]}.md"
    destino.write_text(texto, encoding="utf-8")
    return destino


def lembrete(cwd):
    script = Path(__file__).resolve()
    texto = (
        "diario-de-sessao: ao tomar uma decisão relevante ou deixar algo para depois, registre com "
        f'`python3 "{script}" anotar decisao "..."` ou `anotar pendencia "..."`. Elas entram no diário desta sessão.'
    )
    lista = diarios(cwd)
    if lista:
        texto += f" Há um diário da sessão anterior ({lista[-1].stem}); se o usuário quiser continuar, use /retomar."
    return texto


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gravar")
    sub.add_parser("lembrete")
    p = sub.add_parser("anotar")
    p.add_argument("tipo", choices=sorted(TIPOS_NOTA))
    p.add_argument("texto", nargs="+")
    p = sub.add_parser("ultimo")
    p.add_argument("--caminho", action="store_true", help="só o caminho do arquivo")
    p = sub.add_parser("listar")
    p.add_argument("--n", type=int, default=10)
    a = ap.parse_args()

    if a.cmd in ("gravar", "lembrete"):
        try:
            dados = json.load(sys.stdin)
        except ValueError:
            dados = {}
        if a.cmd == "gravar":
            gravar(dados)
        else:
            print(lembrete(dados.get("cwd") or "."))
        return

    cwd = cwd_da_sessao(Path.cwd())
    if a.cmd == "anotar":
        anotar(cwd, a.tipo, " ".join(a.texto))
        print(f"Anotado: {a.tipo}.")
    elif a.cmd == "ultimo":
        lista = diarios(cwd)
        if not lista:
            sys.exit(f"Nenhum diário para {raiz(cwd)}.")
        print(lista[-1] if a.caminho else lista[-1].read_text(encoding="utf-8"))
    elif a.cmd == "listar":
        lista = diarios(cwd)
        if not lista:
            sys.exit(f"Nenhum diário para {raiz(cwd)}.")
        for arq in lista[-a.n:]:
            print(arq)


if __name__ == "__main__":
    main()
