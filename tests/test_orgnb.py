"""Testes do conversor org <-> ipynb.

O que realmente importa aqui é a estabilidade de ida e volta: o pipeline só é
confiável se ``org -> ipynb -> org`` devolver o arquivo original byte a byte,
porque é isso que impede o ``make sync`` de gerar diffs espúrios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from censo_escolar import orgnb

ORG_EXEMPLO = """\
#+title: Exemplo
#+property: header-args:jupyter-python :session censo :async yes

* Primeira seção

Um parágrafo com =código=, *negrito*, /itálico/ e um
[[https://www.gov.br/inep][link para o INEP]].

#+begin_src jupyter-python :results value
import pandas as pd

df = pd.DataFrame({"a": [1, 2]})
df
#+end_src

** Subseção

- item um
- item dois

#+begin_src jupyter-python
df.sum()
#+end_src

Texto final.
"""


def test_roundtrip_org_preserva_o_arquivo():
    nb = orgnb.org_para_notebook(ORG_EXEMPLO)
    de_volta = orgnb.notebook_para_org(nb)
    assert de_volta == ORG_EXEMPLO


def test_blocos_de_codigo_viram_celulas_code():
    nb = orgnb.org_para_notebook(ORG_EXEMPLO)
    codigo = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(codigo) == 2
    assert "import pandas as pd" in "".join(codigo[0]["source"])


def test_argumentos_de_cabecalho_sobrevivem():
    nb = orgnb.org_para_notebook(ORG_EXEMPLO)
    codigo = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert codigo[0]["metadata"]["org"]["args"] == ":results value"
    # Bloco sem argumentos não inventa nenhum.
    assert "args" not in codigo[1]["metadata"]["org"]


def test_preambulo_vai_para_metadata():
    nb = orgnb.org_para_notebook(ORG_EXEMPLO)
    assert nb["metadata"]["org"]["preamble"][0] == "#+title: Exemplo"
    assert not nb["cells"][0]["source"][0].startswith("#+")


def test_blocos_results_sao_descartados():
    org = (
        "* T\n\n#+begin_src jupyter-python\n1 + 1\n#+end_src\n\n"
        "#+RESULTS:\n: 2\n\nDepois.\n"
    )
    nb = orgnb.org_para_notebook(org)
    texto = json.dumps(nb, ensure_ascii=False)
    assert "RESULTS" not in texto
    assert "Depois." in texto


@pytest.mark.parametrize(
    "org",
    [
        "#+RESULTS:\n#+begin_example\nsaída longa\n#+end_example",
        "#+RESULTS:\n| a | b |\n| 1 | 2 |",
        "#+RESULTS:\n[[file:fig.png]]",
        "#+RESULTS:\nsaída solta",
    ],
)
def test_formatos_de_results(org):
    fonte = f"* T\n\n#+begin_src jupyter-python\nx\n#+end_src\n\n{org}\n\nFim.\n"
    nb = orgnb.org_para_notebook(fonte)
    markdown = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
    assert "saída" not in json.dumps(markdown, ensure_ascii=False)
    assert "Fim." in json.dumps(markdown, ensure_ascii=False)


def test_titulos_viram_headings_markdown():
    nb = orgnb.org_para_notebook(ORG_EXEMPLO)
    md = "".join(nb["cells"][0]["source"])
    assert md.startswith("# Primeira seção")


def test_marcacao_inline_convertida():
    md = orgnb.org_para_md("Use =foo=, *forte*, /leve/ e [[http://x.y][ali]].")
    assert md == "Use `foo`, **forte**, *leve* e [ali](http://x.y)."


def test_marcacao_inline_volta():
    org = orgnb.md_para_org("Use `foo`, **forte**, *leve* e [ali](http://x.y).")
    assert org == "Use =foo=, *forte*, /leve/ e [[http://x.y][ali]]."


def test_barra_em_caminho_nao_vira_italico():
    assert orgnb.org_para_md("veja data/raw/arquivo.csv") == "veja data/raw/arquivo.csv"


def test_linguagem_nao_python_vira_bloco_markdown():
    org = "* T\n\n#+begin_src emacs-lisp\n(+ 1 1)\n#+end_src\n"
    nb = orgnb.org_para_notebook(org)
    assert all(c["cell_type"] == "markdown" for c in nb["cells"])
    assert "```emacs-lisp" in "".join(nb["cells"][0]["source"])
    assert orgnb.notebook_para_org(nb) == org


def test_edicao_no_jupyter_e_traduzida_de_volta():
    nb = orgnb.org_para_notebook(ORG_EXEMPLO)
    alvo = nb["cells"][0]
    alvo["source"] = orgnb._para_source("# Primeira seção\n\nTexto **novo** do Jupyter.")
    org = orgnb.notebook_para_org(nb)
    assert "* Primeira seção" in org
    assert "Texto *novo* do Jupyter." in org


def test_ids_e_saidas_sao_reaproveitados(tmp_path):
    destino = tmp_path / "n.ipynb"
    texto = orgnb.org_para_ipynb_texto(ORG_EXEMPLO, anterior=destino)
    destino.write_text(texto, encoding="utf-8")

    # Simula uma execução no Jupyter: aparecem saídas e execution_count.
    nb = json.loads(destino.read_text(encoding="utf-8"))
    codigo = next(c for c in nb["cells"] if c["cell_type"] == "code")
    codigo["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["oi\n"]}]
    codigo["execution_count"] = 7
    id_original = codigo["id"]
    destino.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")

    # Reconverter a partir do org não pode apagar a saída nem trocar o id.
    novo = json.loads(orgnb.org_para_ipynb_texto(ORG_EXEMPLO, anterior=destino))
    codigo_novo = next(c for c in novo["cells"] if c["cell_type"] == "code")
    assert codigo_novo["outputs"] == codigo["outputs"]
    assert codigo_novo["execution_count"] == 7
    assert codigo_novo["id"] == id_original


def test_ids_sao_deterministicos():
    a = json.loads(orgnb.org_para_ipynb_texto(ORG_EXEMPLO))
    b = json.loads(orgnb.org_para_ipynb_texto(ORG_EXEMPLO))
    assert [c["id"] for c in a["cells"]] == [c["id"] for c in b["cells"]]


def test_sync_ida_e_volta_em_disco(tmp_path):
    org = tmp_path / "doc.org"
    org.write_text(ORG_EXEMPLO, encoding="utf-8")

    assert orgnb.sincronizar(tmp_path) == 1  # criou o .ipynb
    assert (tmp_path / "doc.ipynb").exists()
    assert orgnb.sincronizar(tmp_path, checar=True) == 0  # estável

    # Edita o lado do notebook e sincroniza de volta.
    ipynb = tmp_path / "doc.ipynb"
    nb = json.loads(ipynb.read_text(encoding="utf-8"))
    codigo = next(c for c in nb["cells"] if c["cell_type"] == "code")
    codigo["source"] = ["import pandas as pd\n", "\n", "df = None\n"]
    ipynb.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")

    assert orgnb.sincronizar(tmp_path) >= 1
    assert "df = None" in org.read_text(encoding="utf-8")


def test_conversao_aceita_diretorio(tmp_path):
    """Converter um diretório inteiro é o que substituiu o laço de shell no
    Makefile — sem isto, ``make nb`` não teria tradução para o ``cmd.exe``."""
    for nome in ("a", "b"):
        (tmp_path / f"{nome}.org").write_text(ORG_EXEMPLO, encoding="utf-8")
    (tmp_path / "ignorar.txt").write_text("não é org", encoding="utf-8")

    assert orgnb.main(["org2nb", str(tmp_path)]) == 0
    assert (tmp_path / "a.ipynb").exists()
    assert (tmp_path / "b.ipynb").exists()
    assert not (tmp_path / "ignorar.ipynb").exists()

    assert orgnb.main(["nb2org", str(tmp_path)]) == 0
    assert (tmp_path / "a.org").read_text(encoding="utf-8") == ORG_EXEMPLO


def test_diretorio_sem_arquivos_falha_com_recado(tmp_path, capsys):
    assert orgnb.main(["org2nb", str(tmp_path)]) == 1
    assert "nenhum arquivo .org" in capsys.readouterr().err


def test_saida_explicita_recusa_diretorio(tmp_path):
    (tmp_path / "a.org").write_text(ORG_EXEMPLO, encoding="utf-8")
    with pytest.raises(SystemExit):
        orgnb.main(["org2nb", str(tmp_path), "-o", str(tmp_path / "x.ipynb")])


def test_arquivos_gravados_nao_tem_cr(tmp_path):
    orgnb.org2nb(_org_em(tmp_path, "doc"))
    orgnb.nb2org(tmp_path / "doc.ipynb", tmp_path / "volta.org")
    for nome in ("doc.ipynb", "volta.org"):
        assert b"\r" not in (tmp_path / nome).read_bytes()


def test_gravacao_pede_lf_explicitamente(tmp_path, monkeypatch):
    """Guarda contra a regressão de CRLF no Windows.

    A tradução ``\\n`` -> ``\\r\\n`` só acontece no Windows, e os testes rodam
    aqui — então o efeito é invisível para nós. O que dá para verificar em
    qualquer plataforma é que a gravação *pede* ``\\n``, que é justamente a
    linha de defesa que alguém poderia remover sem quebrar nada localmente.
    """
    _org_em(tmp_path, "doc")  # antes do espião: o setup não é o que medimos

    pedidos: list[str | None] = []
    original = Path.write_text

    def espiao(self, data, **kwargs):
        pedidos.append(kwargs.get("newline"))
        return original(self, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", espiao)
    orgnb.sincronizar(tmp_path)

    assert pedidos and all(p == "\n" for p in pedidos)


def _org_em(diretorio, nome):
    caminho = diretorio / f"{nome}.org"
    caminho.write_text(ORG_EXEMPLO, encoding="utf-8")
    return caminho


def test_notebook_sem_metadata_org_gera_org_utilizavel():
    nb = {
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# Título\n", "\n", "Prosa."]},
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": ["1 + 1"],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    org = orgnb.notebook_para_org(nb, nome="teste")
    assert "#+title: teste" in org
    assert "* Título" in org
    assert f"#+begin_src {orgnb.LANG_PADRAO}" in org
