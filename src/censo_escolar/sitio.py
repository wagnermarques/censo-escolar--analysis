"""Montagem do site estático: páginas de mapa, índice e a lista de consultas.

O site inteiro é *função de um arquivo*: ``site/consultas.txt``, uma linha por
mapa, com exatamente o que se digitou no ``make map`` (R8 do
``georef-plan.org``). Daí decorre tudo o que importa aqui — ``censo site``
relê a lista e reassa tudo, o ``index.html`` é gerado dela e nunca editado à
mão, apagar um mapa é apagar uma linha, e o ``git diff`` mostra quais mapas
entraram, saíram ou mudaram.

Os modelos de página são arquivos em ``templates/`` com marcadores
``{{CHAVE}}``. Marcador, e não ``str.format`` nem f-string, porque o HTML está
cheio de ``{`` de CSS e de ``${}`` de JavaScript — qualquer formatação do
Python brigaria com eles.
"""

from __future__ import annotations

import html
import json
import re
import shlex
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path

from censo_escolar.config import Paths, get_paths

#: Nome do arquivo que define o site. Fica versionado: é o código-fonte.
NOME_CONSULTAS = "consultas.txt"

#: Onde o Leaflet vendorado é procurado. Sem CDN: o site tem de funcionar
#: offline no desenvolvimento e não pode quebrar se um CDN mudar.
VENDOR = ("leaflet.js", "leaflet.css")


@dataclass(frozen=True)
class Consulta:
    """Uma linha de ``consultas.txt`` — um mapa do site."""

    variavel: str
    url: str
    anos: list[int]
    opcoes: dict[str, str]

    def linha(self) -> str:
        # shlex.quote em cada pedaço porque TITULO="Escolas privadas" tem
        # espaço: sem aspas, a releitura quebraria o valor em palavras soltas.
        partes = [self.variavel, shlex.quote(self.url)]
        partes += [str(a) for a in self.anos]
        partes += [shlex.quote(f"{chave}={valor}") for chave, valor in sorted(self.opcoes.items())]
        return " ".join(partes)


def dir_site(paths: Paths | None = None) -> Path:
    return (paths or get_paths()).raiz / "site"


def caminho_consultas(paths: Paths | None = None) -> Path:
    return dir_site(paths) / NOME_CONSULTAS


def analisar_linha(linha: str) -> Consulta | None:
    """Lê uma linha de ``consultas.txt``; devolve ``None`` para vazias e comentários."""
    sem_comentario = linha.split("#", 1)[0].strip() if not linha.strip().startswith("#") else ""
    if not sem_comentario:
        return None
    palavras = shlex.split(sem_comentario)
    variavel = ""
    url = ""
    anos: list[int] = []
    opcoes: dict[str, str] = {}
    for palavra in palavras:
        if palavra.startswith("http"):
            url = palavra
        elif re.fullmatch(r"(19|20)\d{2}", palavra):
            anos.append(int(palavra))
        elif "=" in palavra:
            chave, valor = palavra.split("=", 1)
            opcoes[chave.upper()] = valor
        elif not variavel:
            variavel = palavra.upper()
    if not variavel or not url:
        raise ValueError(f"linha sem variável ou sem URL: {linha.strip()!r}")
    return Consulta(variavel=variavel, url=url, anos=sorted(anos), opcoes=opcoes)


def ler_consultas(*, paths: Paths | None = None) -> list[Consulta]:
    arquivo = caminho_consultas(paths)
    if not arquivo.exists():
        return []
    consultas = []
    for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            consulta = analisar_linha(linha)
        except ValueError as erro:
            raise ValueError(f"{arquivo}:{numero}: {erro}") from erro
        if consulta:
            consultas.append(consulta)
    return consultas


def registrar_consulta(consulta: Consulta, *, paths: Paths | None = None) -> Path:
    """Acrescenta (ou atualiza) a linha da consulta em ``consultas.txt``.

    A identidade é (variável, URL): rodar de novo com outros anos atualiza a
    linha em vez de duplicá-la — a mesma ideia do nome determinístico do
    arquivo de saída.
    """
    arquivo = caminho_consultas(paths)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if not arquivo.exists():
        arquivo.write_text(
            "# Uma linha por mapa: <VARIAVEL> \"<URL da malha IBGE>\" [anos] [OPCAO=valor]\n"
            "# Gerado e lido por `make map` / `make site`. Editável à mão.\n",
            encoding="utf-8",
        )

    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    saida: list[str] = []
    trocou = False
    for linha in linhas:
        try:
            existente = analisar_linha(linha)
        except ValueError:
            existente = None
        if existente and (existente.variavel, existente.url) == (consulta.variavel, consulta.url):
            if not trocou:
                saida.append(consulta.linha())
                trocou = True
            continue
        saida.append(linha)
    if not trocou:
        saida.append(consulta.linha())
    arquivo.write_text("\n".join(saida) + "\n", encoding="utf-8")
    return arquivo


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------


def _modelo(nome: str) -> str:
    return resources.files("censo_escolar.templates").joinpath(nome).read_text(encoding="utf-8")


def _preencher(modelo: str, valores: dict[str, str]) -> str:
    for chave, valor in valores.items():
        modelo = modelo.replace("{{" + chave + "}}", valor)
        modelo = modelo.replace("{{" + chave + "|json}}", json.dumps(valor, ensure_ascii=False))
    return modelo


def escrever_pagina(
    slug: str,
    *,
    titulo: str,
    subtitulo: str,
    descricao: str,
    rodape: str,
    anos: list[int],
    unidade: str,
    paths: Paths | None = None,
) -> Path:
    """Grava ``site/mapas/<slug>.html`` a partir do modelo único."""
    destino = dir_site(paths) / "mapas" / f"{slug}.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        _preencher(
            _modelo("mapa.html"),
            {
                "TITULO": html.escape(titulo),
                "SUBTITULO": html.escape(subtitulo),
                "DESCRICAO": html.escape(descricao),
                "RODAPE": rodape,
                "SLUG": slug,
                "ANOS": json.dumps(anos),
                "UNIDADE": html.escape(unidade),
            },
        ),
        encoding="utf-8",
    )
    return destino


#: Metadados dos mapas já assados. É artefato de build (o índice é gerado
#: dele), e não fonte: quem manda é o ``consultas.txt``.
NOME_INDICE = "mapas.json"


def caminho_indice(paths: Paths | None = None) -> Path:
    return dir_site(paths) / NOME_INDICE


def ler_indice(*, paths: Paths | None = None) -> list[dict]:
    arquivo = caminho_indice(paths)
    if not arquivo.exists():
        return []
    return json.loads(arquivo.read_text(encoding="utf-8"))


def atualizar_indice(entrada: dict, *, paths: Paths | None = None) -> list[dict]:
    """Insere ou substitui um mapa no índice, mantendo a ordem de inclusão."""
    atual = [m for m in ler_indice(paths=paths) if m["slug"] != entrada["slug"]]
    atual.append(entrada)
    return escrever_indice(atual, paths=paths)


def escrever_indice(entradas: list[dict], *, paths: Paths | None = None) -> list[dict]:
    arquivo = caminho_indice(paths)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(entradas, ensure_ascii=False, indent=1), encoding="utf-8")
    return entradas


def entrada_de_indice(resultado: dict) -> dict:
    """Só o que o índice precisa — sem os Path, que não são JSON."""
    return {
        chave: resultado[chave]
        for chave in ("slug", "titulo", "descricao", "variavel", "anos", "grao", "areas")
    }


def gerar_index(mapas: list[dict], *, paths: Paths | None = None) -> Path:
    """Gera ``site/index.html`` a partir da lista de mapas assados."""
    itens = []
    for mapa in mapas:
        anos = mapa["anos"]
        faixa = f"{anos[0]}–{anos[-1]}" if len(anos) > 1 else str(anos[0])
        itens.append(
            "<li class=\"cartao\">"
            f'<a href="mapas/{html.escape(mapa["slug"])}.html">'
            f'<strong>{html.escape(mapa["titulo"])}</strong></a>'
            f'<p>{html.escape(mapa.get("descricao", ""))}</p>'
            f'<p class="meta">{html.escape(mapa["variavel"])} · {html.escape(faixa)} · '
            f'{html.escape(mapa.get("grao", ""))} · {mapa.get("areas", 0)} áreas</p>'
            "</li>"
        )
    destino = dir_site(paths) / "index.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        _preencher(
            _modelo("index.html"),
            {
                "ITENS": "\n".join(itens) or "<li class='cartao'>Nenhum mapa ainda.</li>",
                "N": str(len(mapas)),
                "GERADO_EM": date.today().isoformat(),
            },
        ),
        encoding="utf-8",
    )
    return destino


def garantir_vendor(*, paths: Paths | None = None) -> Path:
    """Copia o Leaflet vendorado do pacote para ``site/vendor/``."""
    destino = dir_site(paths) / "vendor"
    destino.mkdir(parents=True, exist_ok=True)
    origem = resources.files("censo_escolar.vendor")
    for nome in VENDOR:
        alvo = destino / nome
        if not alvo.exists():
            alvo.write_bytes(origem.joinpath(nome).read_bytes())
    return destino
