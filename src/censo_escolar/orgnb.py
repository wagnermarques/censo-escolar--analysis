"""Conversão bidirecional entre documentos org-mode e notebooks Jupyter.

Por que existe: o ``jupytext`` cobre Markdown, MyST, Rmd, Quarto e scripts
``py:percent``, mas **não** cobre org-mode. O ``pandoc`` até converte
``org`` ⇄ ``ipynb``, mas perde os argumentos de cabeçalho dos blocos
(``:session``, ``:results``, ``:var``) — que é justamente o que faz o
org-babel funcionar. Este módulo é pequeno o bastante para ser lido inteiro e
preserva o que importa nos dois sentidos.

Mapeamento
----------
=========================================  =========================================
org                                        ipynb
=========================================  =========================================
``#+begin_src jupyter-python ARGS``        célula ``code``; ``ARGS`` vai para
                                           ``metadata.org.args``
``#+begin_src <outra-linguagem>``          bloco cercado dentro de célula markdown
títulos ``*``/``**``, prosa, listas        célula ``markdown``
``#+RESULTS:`` e seu conteúdo              descartado (a saída vive no ipynb)
palavras-chave do topo (``#+title:`` …)    ``metadata.org.preamble``
=========================================  =========================================

Fidelidade de ida e volta
-------------------------
As células markdown guardam o org original em ``metadata.org.src``. Na volta
(ipynb → org), se o markdown da célula ainda for exatamente o que aquele org
gera, o org original é reemitido tal e qual — então formatação org sem
equivalente em markdown sobrevive a ciclos em que ninguém editou o texto no
Jupyter. Se alguém editou, aí sim traduzimos markdown → org.

Uso::

    python -m censo_escolar.orgnb org2nb notebooks/01-panorama.org
    python -m censo_escolar.orgnb nb2org notebooks/01-panorama.ipynb
    python -m censo_escolar.orgnb org2nb notebooks/        # diretório inteiro
    python -m censo_escolar.orgnb sync notebooks/          # pelo mtime
    python -m censo_escolar.orgnb sync notebooks/ --check  # sai 1 se dessincronizado
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

#: Linguagens de bloco org que viram célula de código executável.
LINGUAGENS_CODIGO = frozenset({"python", "jupyter-python", "ipython", "python3"})

#: Linguagem emitida ao gerar org a partir de um ipynb sem essa informação.
LANG_PADRAO = "jupyter-python"

#: Argumentos de cabeçalho emitidos para blocos que não trazem os seus.
ARGS_PADRAO = ""

KERNELSPEC_PADRAO = {"display_name": "Python 3", "language": "python", "name": "python3"}

_RE_BEGIN_BLOCO = re.compile(r"^[ \t]*#\+begin_(\w+)\b(.*)$", re.IGNORECASE)
_RE_END_BLOCO = re.compile(r"^[ \t]*#\+end_(\w+)[ \t]*$", re.IGNORECASE)
_RE_BEGIN_SRC = re.compile(r"^[ \t]*#\+begin_src[ \t]*(\S*)[ \t]*(.*)$", re.IGNORECASE)
_RE_RESULTS = re.compile(r"^[ \t]*#\+RESULTS:", re.IGNORECASE)
_RE_KEYWORD = re.compile(r"^[ \t]*#\+[\w-]+:")
_RE_TITULO_ORG = re.compile(r"^(\*+)[ \t]+(.*)$")
_RE_TITULO_MD = re.compile(r"^(#{1,8})[ \t]+(.*)$")

# --------------------------------------------------------------------------
# Conversão de marcação inline
# --------------------------------------------------------------------------

_ORG_INLINE = re.compile(
    r"(?P<link>\[\[(?P<alvo>[^\]\[]+)\](?:\[(?P<rotulo>[^\]]+)\])?\])"
    r"|(?P<verb>(?<![\w=])=(?P<verb_t>[^=\n]+)=(?![\w=]))"
    r"|(?P<code>(?<![\w~])~(?P<code_t>[^~\n]+)~(?![\w~]))"
    r"|(?P<bold>(?<![\w*])\*(?P<bold_t>[^*\n]+)\*(?![\w*]))"
    r"|(?P<ital>(?<![\w/])/(?P<ital_t>[^/\n]+)/(?![\w/]))"
)

_MD_INLINE = re.compile(
    r"(?P<code>`(?P<code_t>[^`\n]+)`)"
    r"|(?P<link>\[(?P<rotulo>[^\]]*)\]\((?P<alvo>[^)\s]+)\))"
    r"|(?P<auto><(?P<url>[a-z][a-z0-9+.-]*:[^>\s]+)>)"
    r"|(?P<bold>(?<![\w*])\*\*(?P<bold_t>[^*\n]+)\*\*)"
    r"|(?P<ital>(?<![\w*])\*(?P<ital_t>[^*\n]+)\*(?![\w*]))"
)


def _inline_org_para_md(linha: str) -> str:
    def troca(m: re.Match[str]) -> str:
        if m.group("link"):
            alvo = m.group("alvo")
            alvo = alvo[5:] if alvo.startswith("file:") else alvo
            rotulo = m.group("rotulo")
            return f"[{rotulo}]({alvo})" if rotulo else f"<{alvo}>"
        if m.group("verb"):
            return f"`{m.group('verb_t')}`"
        if m.group("code"):
            return f"`{m.group('code_t')}`"
        if m.group("bold"):
            return f"**{m.group('bold_t')}**"
        return f"*{m.group('ital_t')}*"

    return _ORG_INLINE.sub(troca, linha)


def _inline_md_para_org(linha: str) -> str:
    def troca(m: re.Match[str]) -> str:
        if m.group("code"):
            return f"={m.group('code_t')}="
        if m.group("link"):
            rotulo, alvo = m.group("rotulo"), m.group("alvo")
            if not re.match(r"^[a-z][a-z0-9+.-]*:", alvo):
                alvo = "file:" + alvo
            return f"[[{alvo}][{rotulo}]]" if rotulo else f"[[{alvo}]]"
        if m.group("auto"):
            return f"[[{m.group('url')}]]"
        if m.group("bold"):
            return f"*{m.group('bold_t')}*"
        return f"/{m.group('ital_t')}/"

    return _MD_INLINE.sub(troca, linha)


def org_para_md(texto: str) -> str:
    """Converte um trecho de prosa org em markdown."""
    saida: list[str] = []
    bloco: str | None = None  # tipo do bloco org aberto, se houver
    for linha in texto.split("\n"):
        if bloco is not None:
            if _RE_END_BLOCO.match(linha):
                if bloco != "quote":
                    saida.append("```")
                bloco = None
                continue
            saida.append(f"> {linha}" if bloco == "quote" else linha)
            continue

        inicio = _RE_BEGIN_BLOCO.match(linha)
        if inicio:
            bloco = inicio.group(1).lower()
            if bloco == "quote":
                pass
            elif bloco == "src":
                src = _RE_BEGIN_SRC.match(linha)
                saida.append("```" + (src.group(1) if src else ""))
            else:
                saida.append("```")
            continue

        titulo = _RE_TITULO_ORG.match(linha)
        if titulo:
            saida.append("#" * len(titulo.group(1)) + " " + _inline_org_para_md(titulo.group(2)))
            continue

        if _RE_KEYWORD.match(linha):
            # Palavras-chave org não têm equivalente em markdown; o org original
            # fica em metadata.org.src, então nada se perde de fato.
            continue

        saida.append(_inline_org_para_md(linha))

    return "\n".join(saida).strip("\n")


def md_para_org(texto: str) -> str:
    """Converte markdown em org. Usado quando a célula foi editada no Jupyter."""
    saida: list[str] = []
    cerca: str | None = None  # None = fora de bloco; "" = example; senão, linguagem
    for linha in texto.split("\n"):
        if cerca is not None:
            if linha.lstrip().startswith("```"):
                saida.append("#+end_src" if cerca else "#+end_example")
                cerca = None
            else:
                saida.append(linha)
            continue

        if linha.lstrip().startswith("```"):
            lang = linha.strip()[3:].strip()
            saida.append(f"#+begin_src {lang}" if lang else "#+begin_example")
            cerca = lang
            continue

        titulo = _RE_TITULO_MD.match(linha)
        if titulo:
            saida.append("*" * len(titulo.group(1)) + " " + _inline_md_para_org(titulo.group(2)))
            continue

        saida.append(_inline_md_para_org(linha))

    if cerca is not None:  # bloco não fechado no markdown
        saida.append("#+end_src" if cerca else "#+end_example")
    return "\n".join(saida).strip("\n")


# --------------------------------------------------------------------------
# org -> ipynb
# --------------------------------------------------------------------------


def _para_source(texto: str) -> list[str]:
    """Texto -> lista de linhas no formato nbformat (``\\n`` no fim, menos a última)."""
    linhas = texto.split("\n")
    return [linha + "\n" for linha in linhas[:-1]] + linhas[-1:]


def _consumir_results(linhas: list[str], i: int) -> int:
    """Devolve o índice logo após o bloco ``#+RESULTS:`` que começa em ``i``."""
    i += 1
    if i >= len(linhas):
        return i
    atual = linhas[i].lstrip()
    if atual.startswith("#+begin_"):
        while i < len(linhas) and not _RE_END_BLOCO.match(linhas[i]):
            i += 1
        return i + 1
    if atual.startswith((":", "|", "[[")):
        prefixos = (":", "|", "[[")
        while i < len(linhas) and linhas[i].lstrip().startswith(prefixos):
            i += 1
        return i
    # Saída solta: vai até a primeira linha em branco.
    while i < len(linhas) and linhas[i].strip():
        i += 1
    return i


def org_para_notebook(texto: str, *, titulo_arquivo: str = "") -> dict[str, Any]:
    """Converte o conteúdo de um arquivo ``.org`` em um dicionário nbformat."""
    linhas = texto.split("\n")
    celulas: list[dict[str, Any]] = []
    preambulo: list[str] = []
    buffer_md: list[str] = []
    lang_padrao = LANG_PADRAO

    # Preâmbulo: palavras-chave e comentários no topo, antes de qualquer conteúdo.
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        if _RE_KEYWORD.match(linha) and not _RE_BEGIN_BLOCO.match(linha):
            preambulo.append(linha)
            i += 1
        elif not linha.strip() and preambulo:
            preambulo.append(linha)
            i += 1
        elif not linha.strip():
            i += 1
        else:
            break
    while preambulo and not preambulo[-1].strip():
        preambulo.pop()

    def descarregar_md() -> None:
        bruto = "\n".join(buffer_md).strip("\n")
        buffer_md.clear()
        if not bruto.strip():
            return
        celulas.append(
            {
                "cell_type": "markdown",
                "metadata": {"org": {"src": bruto}},
                "source": _para_source(org_para_md(bruto)),
            }
        )

    while i < len(linhas):
        linha = linhas[i]

        if _RE_RESULTS.match(linha):
            i = _consumir_results(linhas, i)
            continue

        src = _RE_BEGIN_SRC.match(linha)
        if src:
            lang, args = src.group(1).lower(), src.group(2).strip()
            corpo: list[str] = []
            j = i + 1
            while j < len(linhas) and not _RE_END_BLOCO.match(linhas[j]):
                corpo.append(linhas[j])
                j += 1
            if lang in LINGUAGENS_CODIGO:
                descarregar_md()
                lang_padrao = lang
                meta: dict[str, Any] = {"org": {"lang": lang}}
                if args:
                    meta["org"]["args"] = args
                celulas.append(
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": meta,
                        "outputs": [],
                        "source": _para_source("\n".join(corpo).strip("\n")),
                    }
                )
            else:
                # Outras linguagens seguem como texto: viram bloco cercado no md.
                buffer_md.extend(linhas[i : j + 1])
            i = j + 1
            continue

        buffer_md.append(linha)
        i += 1

    descarregar_md()

    metadata: dict[str, Any] = {
        "kernelspec": dict(KERNELSPEC_PADRAO),
        "language_info": {"name": "python"},
        "org": {"preamble": preambulo, "lang_padrao": lang_padrao},
    }
    if titulo_arquivo:
        metadata["org"]["arquivo"] = titulo_arquivo
    return {"cells": celulas, "metadata": metadata, "nbformat": 4, "nbformat_minor": 5}


def _reaproveitar(celulas: list[dict[str, Any]], anterior: Path) -> None:
    """Traz ids, saídas e ``execution_count`` do ipynb já existente.

    Sem isso, cada conversão zeraria as saídas e trocaria todos os ids —
    transformando qualquer edição de uma linha num diff do arquivo inteiro.
    """
    if not anterior.exists():
        return
    try:
        antigo = json.loads(anterior.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    mapa: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for celula in antigo.get("cells", []):
        chave = (celula.get("cell_type", ""), "".join(celula.get("source", [])))
        mapa.setdefault(chave, []).append(celula)

    for celula in celulas:
        chave = (celula["cell_type"], "".join(celula["source"]))
        fila = mapa.get(chave)
        if not fila:
            continue
        velha = fila.pop(0)
        if "id" in velha:
            celula["id"] = velha["id"]
        if celula["cell_type"] == "code":
            celula["outputs"] = velha.get("outputs", [])
            celula["execution_count"] = velha.get("execution_count")


def _atribuir_ids(celulas: list[dict[str, Any]]) -> None:
    """Preenche os ids faltantes de forma determinística (nbformat >= 4.5)."""
    usados = {c["id"] for c in celulas if "id" in c}
    for celula in celulas:
        if "id" in celula:
            continue
        digest = hashlib.sha1("".join(celula["source"]).encode("utf-8")).hexdigest()[:8]
        cid, n = digest, 1
        while cid in usados:
            cid = f"{digest}-{n}"
            n += 1
        usados.add(cid)
        celula["id"] = cid


def org_para_ipynb_texto(texto_org: str, *, anterior: Path | None = None, nome: str = "") -> str:
    """org (texto) -> JSON do notebook (texto), pronto para gravar."""
    nb = org_para_notebook(texto_org, titulo_arquivo=nome)
    if anterior is not None:
        _reaproveitar(nb["cells"], anterior)
    _atribuir_ids(nb["cells"])
    return json.dumps(nb, ensure_ascii=False, indent=1) + "\n"


# --------------------------------------------------------------------------
# ipynb -> org
# --------------------------------------------------------------------------


def notebook_para_org(nb: dict[str, Any], *, nome: str = "") -> str:
    """Converte um dicionário nbformat em texto org."""
    meta_org = nb.get("metadata", {}).get("org", {})
    preambulo: list[str] = list(meta_org.get("preamble") or [])
    lang_padrao = meta_org.get("lang_padrao") or LANG_PADRAO

    # A chave "preamble" só existe em notebooks que vieram de um .org. Sem ela,
    # o notebook nasceu no Jupyter e precisa de um cabeçalho org utilizável —
    # com ela, um preâmbulo vazio é uma escolha do autor e deve ser respeitada.
    if not preambulo and "preamble" not in meta_org:
        titulo = nome or "Análise"
        preambulo = [
            f"#+title: {titulo}",
            f"#+property: header-args:{lang_padrao} :session censo :async yes :exports both",
        ]

    partes: list[str] = ["\n".join(preambulo)]

    for celula in nb.get("cells", []):
        fonte = "".join(celula.get("source", []))
        if celula.get("cell_type") == "code":
            org = celula.get("metadata", {}).get("org", {})
            lang = org.get("lang") or lang_padrao
            args = org.get("args", ARGS_PADRAO)
            cabecalho = f"#+begin_src {lang}" + (f" {args}" if args else "")
            partes.append(f"{cabecalho}\n{fonte}\n#+end_src")
        else:
            guardado = celula.get("metadata", {}).get("org", {}).get("src")
            if guardado is not None and org_para_md(guardado) == fonte:
                partes.append(guardado)
            else:
                partes.append(md_para_org(fonte))

    return "\n\n".join(p for p in partes if p.strip()) + "\n"


def ipynb_para_org_texto(texto_ipynb: str, *, nome: str = "") -> str:
    """ipynb (texto JSON) -> org (texto)."""
    return notebook_para_org(json.loads(texto_ipynb), nome=nome)


# --------------------------------------------------------------------------
# Operações sobre arquivos
# --------------------------------------------------------------------------


#: Gravamos sempre com ``\n``, nunca com o final de linha nativo. Sem isto, o
#: modo texto do Python traduziria para ``\r\n`` no Windows: o arquivo mudaria
#: por inteiro só de atravessar um sistema operacional, e cada `sync` viraria um
#: diff do arquivo inteiro no git. O `.gitattributes` cuida do outro lado.
_NL = "\n"


def _gravar(destino: Path, texto: str) -> Path:
    """Grava texto UTF-8 com finais de linha ``\\n`` em qualquer plataforma."""
    destino.write_text(texto, encoding="utf-8", newline=_NL)
    return destino


def org2nb(origem: Path, destino: Path | None = None) -> Path:
    """Converte um ``.org`` no ``.ipynb`` correspondente."""
    destino = destino or origem.with_suffix(".ipynb")
    texto = org_para_ipynb_texto(
        origem.read_text(encoding="utf-8"), anterior=destino, nome=origem.stem
    )
    return _gravar(destino, texto)


def nb2org(origem: Path, destino: Path | None = None) -> Path:
    """Converte um ``.ipynb`` no ``.org`` correspondente."""
    destino = destino or origem.with_suffix(".org")
    texto = ipynb_para_org_texto(origem.read_text(encoding="utf-8"), nome=origem.stem)
    return _gravar(destino, texto)


def _alvos(caminho: Path, sufixo: str) -> list[Path]:
    """Resolve ``caminho`` em uma lista de arquivos a converter.

    Aceita um arquivo ou um diretório. O diretório existe para que o Makefile
    não precise de um laço de shell — ``for f in *.org; do ...; done`` não tem
    tradução no ``cmd.exe``, enquanto um ``glob`` do Python roda igual em toda
    plataforma. A portabilidade fica aqui, onde já era portátil.
    """
    if caminho.is_dir():
        return sorted(caminho.glob(f"*{sufixo}"))
    if not caminho.exists():
        raise FileNotFoundError(f"não encontrado: {caminho}")
    return [caminho]


def _pares(diretorio: Path) -> list[tuple[Path, Path]]:
    """Todos os pares (org, ipynb) do diretório, existindo pelo menos um dos dois."""
    bases = {p.with_suffix("") for p in diretorio.glob("*.org")}
    bases |= {p.with_suffix("") for p in diretorio.glob("*.ipynb")}
    return sorted((b.with_suffix(".org"), b.with_suffix(".ipynb")) for b in bases)


def sincronizar(diretorio: Path, *, checar: bool = False) -> int:
    """Sincroniza os pares ``.org``/``.ipynb`` de um diretório pelo ``mtime``.

    :param checar: não escreve nada; apenas relata pares fora de sincronia.
    :returns: número de pares dessincronizados (0 quando tudo está em ordem).
    """
    pendentes = 0
    for org, ipynb in _pares(diretorio):
        if org.exists() and not ipynb.exists():
            direcao = "org2nb"
        elif ipynb.exists() and not org.exists():
            direcao = "nb2org"
        elif org.stat().st_mtime >= ipynb.stat().st_mtime:
            direcao = "org2nb"
        else:
            direcao = "nb2org"

        if direcao == "org2nb":
            novo = org_para_ipynb_texto(
                org.read_text(encoding="utf-8"), anterior=ipynb, nome=org.stem
            )
            alvo, origem = ipynb, org
        else:
            novo = ipynb_para_org_texto(ipynb.read_text(encoding="utf-8"), nome=ipynb.stem)
            alvo, origem = org, ipynb

        atual = alvo.read_text(encoding="utf-8") if alvo.exists() else None
        if atual == novo:
            continue
        pendentes += 1
        if checar:
            print(f"fora de sincronia: {alvo.name} (fonte mais nova: {origem.name})")
        else:
            _gravar(alvo, novo)
            print(f"{origem.name} -> {alvo.name}")
    return pendentes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orgnb", description="Converte documentos org-mode e notebooks Jupyter."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_org = sub.add_parser("org2nb", help="org -> ipynb (arquivo ou diretório)")
    p_org.add_argument("arquivo", type=Path)
    p_org.add_argument("-o", "--saida", type=Path)

    p_nb = sub.add_parser("nb2org", help="ipynb -> org (arquivo ou diretório)")
    p_nb.add_argument("arquivo", type=Path)
    p_nb.add_argument("-o", "--saida", type=Path)

    p_sync = sub.add_parser("sync", help="sincroniza um diretório pelo mtime")
    p_sync.add_argument("diretorio", type=Path, nargs="?", default=Path("notebooks"))
    p_sync.add_argument(
        "--check", action="store_true", help="não escreve; sai com 1 se houver pendências"
    )

    args = parser.parse_args(argv)

    if args.comando in ("org2nb", "nb2org"):
        converter = org2nb if args.comando == "org2nb" else nb2org
        sufixo = ".org" if args.comando == "org2nb" else ".ipynb"
        try:
            alvos = _alvos(args.arquivo, sufixo)
        except FileNotFoundError as erro:
            parser.error(str(erro))
        if not alvos:
            print(f"nenhum arquivo {sufixo} em {args.arquivo}", file=sys.stderr)
            return 1
        # A recusa olha o argumento, não a contagem: um diretório com um único
        # arquivo hoje pode ter dois amanhã, e aí o -o passaria a sobrescrever
        # a mesma saída em silêncio.
        if args.saida is not None and args.arquivo.is_dir():
            parser.error("--saida só vale para um arquivo, não para um diretório")
        for arquivo in alvos:
            print(converter(arquivo, args.saida))
        return 0

    pendentes = sincronizar(args.diretorio, checar=args.check)
    if args.check and pendentes:
        print(f"\n{pendentes} par(es) fora de sincronia. Rode: make sync", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
