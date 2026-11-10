"""Testes do diario-de-sessao: gravar, anotar, ultimo e lembrete, com HOME e repositório temporários."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "retomar" / "scripts" / "diario.py"
SID = "abcdef12-0000-0000-0000-000000000000"


def assistente(mid, conteudo, modelo="claude-opus-5-5", ts="2026-11-10T12:00:00.000Z", **uso):
    uso = {"input_tokens": 1000, "output_tokens": 1000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, **uso}
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": modelo, "usage": uso, "content": conteudo}}


def usuario(texto, ts="2026-11-10T11:59:00.000Z", **extra):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": texto}, **extra}


class Diario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.repo = base / "repo"
        self.home.mkdir()
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.transcricao = self.home / ".claude" / "projects" / "p" / f"{SID}.jsonl"
        self.transcricao.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def escrever(self, linhas, arquivo=None):
        (arquivo or self.transcricao).write_text("".join(json.dumps(l) + "\n" for l in linhas))

    def rodar(self, *args, entrada=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], input=entrada, capture_output=True, text=True,
            cwd=self.repo, env={**os.environ, "HOME": str(self.home)},
        )

    def gravar(self):
        dados = {"session_id": SID, "transcript_path": str(self.transcricao), "cwd": str(self.repo), "reason": "exit"}
        r = self.rodar("gravar", entrada=json.dumps(dados))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r

    def diario(self):
        r = self.rodar("ultimo")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_diario_completo(self):
        (self.repo / "a.py").write_text("x")
        self.git("add", "a.py")
        self.git("commit", "-q", "-m", "Primeiro commit")
        (self.repo / "b.py").write_text("y")
        self.escrever([
            usuario("Crie o módulo de login"),
            usuario("<command-name>/clear</command-name>"),
            usuario("lembrete", isMeta=True),
            assistente("m1", [
                {"type": "tool_use", "name": "Write", "input": {"file_path": str(self.repo / "a.py")}},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": str(self.repo / "a.py")}},
                {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                    {"content": "Escrever testes", "status": "pending"},
                    {"content": "Criar módulo", "status": "completed"},
                ]}},
            ]),
            assistente("m2", [{"type": "text", "text": "Pronto: login criado."}], ts="2026-11-10T13:30:00.000Z"),
        ])
        self.rodar("anotar", "decisao", "Usar", "bcrypt")
        self.rodar("anotar", "pendencia", "Revisar mensagens de erro")
        self.gravar()
        d = self.diario()
        self.assertIn("- Crie o módulo de login", d)
        self.assertNotIn("/clear", d)
        self.assertNotIn("lembrete", d)
        self.assertIn("- `a.py` (2 edições)", d)
        self.assertIn("Primeiro commit", d)
        self.assertIn("- Usar bcrypt", d)
        self.assertIn("- Revisar mensagens de erro", d)
        self.assertIn("- Escrever testes (pending)", d)
        self.assertNotIn("Criar módulo", d)
        self.assertIn("não commitado(s): `b.py`", d)
        self.assertIn("> Pronto: login criado.", d)
        self.assertIn("- Encerramento: exit", d)

    def test_custo_com_subagentes_e_sem_duplicar(self):
        # Mesmo id em duas linhas conta uma vez; Opus 5.5: 1000 × 4 + 1000 × 20 = US$ 0,024.
        self.escrever([
            assistente("m1", [{"type": "text", "text": "a"}]),
            assistente("m1", [{"type": "text", "text": "b"}]),
            assistente("s", [], modelo="<synthetic>"),
        ])
        sub = self.transcricao.parent / SID / "subagents" / "agente.jsonl"
        sub.parent.mkdir(parents=True)
        self.escrever([assistente("x1", [], modelo="claude-haiku-4-5-20251001", input_tokens=0, output_tokens=1_000_000)], sub)
        self.gravar()
        d = self.diario()
        self.assertIn("| Conversa principal | `claude-opus-5-5` | 1 |", d)
        self.assertIn("| Subagentes (1) | `claude-haiku-4-5-20251001` | 1 |", d)
        self.assertIn("US$ 5,02", d)

    def test_precos_do_usuario(self):
        pasta = self.home / ".claude" / "estimar-tokens"
        pasta.mkdir(parents=True)
        (pasta / "precos.json").write_text(json.dumps({"modelos": {"claude-opus-5-5": {"entrada": 0, "saida": 1000, "leitura_cache": 0}}}))
        self.escrever([assistente("m1", [])])
        self.gravar()
        self.assertIn("- Custo: US$ 1,00", self.diario())

    def test_modelo_sem_preco(self):
        self.escrever([assistente("m1", [], modelo="modelo-novo")])
        self.gravar()
        self.assertIn("Sem preço na tabela (fora do total): `modelo-novo`.", self.diario())

    def test_notas_sao_consumidas(self):
        self.escrever([assistente("m1", [])])
        self.rodar("anotar", "decisao", "Primeira")
        self.gravar()
        self.assertIn("Primeira", self.diario())
        self.escrever([assistente("m2", [], ts="2026-11-10T15:00:00.000Z")])
        self.gravar()
        self.assertNotIn("Primeira", self.diario())

    def test_sessao_vazia_nao_grava(self):
        self.escrever([usuario("oi")])
        self.gravar()
        self.assertEqual(self.rodar("ultimo").returncode, 1)

    def test_entrada_invalida_nao_quebra(self):
        r = self.rodar("gravar", entrada="não é json")
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_subpasta_usa_a_raiz_do_repositorio(self):
        self.escrever([assistente("m1", [])])
        self.gravar()
        sub = self.repo / "src"
        sub.mkdir()
        r = subprocess.run([sys.executable, str(SCRIPT), "ultimo", "--caminho"], capture_output=True, text=True,
                           cwd=sub, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip().endswith(f"_{SID[:8]}.md"))

    def workspace_com_subrepo(self):
        """Pasta sem git (onde a sessão começou) com um repositório dentro, para onde a sessão fez `cd`."""
        ws = Path(self.tmp.name) / "ws"
        sub = ws / "sub"
        sub.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=sub, check=True)
        transcricao = self.home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ws)) / f"{SID}.jsonl"
        transcricao.parent.mkdir(parents=True)
        self.escrever([usuario("oi", cwd=str(ws)), assistente("m1", [])], transcricao)
        return ws, sub, transcricao

    def rodar_em(self, pasta, *args, entrada=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=entrada, capture_output=True, text=True,
                              cwd=pasta, env={**os.environ, "HOME": str(self.home)})

    def test_cd_para_subrepo_nao_muda_o_projeto(self):
        ws, sub, transcricao = self.workspace_com_subrepo()
        self.assertEqual(self.rodar_em(sub, "anotar", "decisao", "Depois do cd").returncode, 0)
        dados = {"session_id": SID, "transcript_path": str(transcricao), "cwd": str(sub), "reason": "exit"}
        self.assertEqual(self.rodar_em(sub, "gravar", entrada=json.dumps(dados)).returncode, 0)
        r = self.rodar_em(ws, "ultimo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Depois do cd", r.stdout)
        self.assertFalse((self.home / ".claude" / "diario-de-sessao" / re.sub(r"[^A-Za-z0-9]", "-", str(sub))).exists())

    def test_lembrete(self):
        r = self.rodar("lembrete", entrada=json.dumps({"cwd": str(self.repo)}))
        self.assertIn("anotar decisao", r.stdout)
        self.assertNotIn("use /retomar", r.stdout)
        self.escrever([assistente("m1", [])])
        self.gravar()
        r = self.rodar("lembrete", entrada=json.dumps({"cwd": str(self.repo)}))
        self.assertIn("use /retomar", r.stdout)

    def test_listar(self):
        self.assertEqual(self.rodar("listar").returncode, 1)
        self.escrever([assistente("m1", [])])
        self.gravar()
        self.assertEqual(len(self.rodar("listar").stdout.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
