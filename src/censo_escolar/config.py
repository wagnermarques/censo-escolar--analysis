"""Caminhos e parâmetros globais do projeto.

Os diretórios são resolvidos a partir da raiz do repositório, e não do
diretório de trabalho corrente. Isso importa: o Jupyter normalmente roda com o
cwd em ``notebooks/``, enquanto o org-babel do Emacs roda com o cwd em qualquer
lugar (depende do ``:dir`` e de onde o Emacs foi aberto). Sem essa resolução, o
mesmo código quebraria em um dos dois ambientes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Arquivos que marcam a raiz do projeto durante a subida de diretórios.
_MARCADORES_RAIZ = ("pyproject.toml", ".git")

#: Sobrepõe a detecção automática da raiz.
ENV_RAIZ = "CENSO_ESCOLAR_ROOT"

#: Sobrepõe apenas o diretório de dados (útil para apontar para um HD externo).
ENV_DATA = "CENSO_ESCOLAR_DATA"

#: Sobrepõe o padrão de URL dos microdados. Use ``{ano}`` como marcador.
ENV_URL = "CENSO_ESCOLAR_URL"

#: Encoding e separador usados pelo INEP nos CSVs de microdados.
ENCODING = "latin-1"
SEPARADOR = ";"

#: Padrão de URL dos microdados. O INEP já mudou host e caminho mais de uma
#: vez; confira em https://www.gov.br/inep/ (Dados Abertos > Microdados) e
#: sobreponha via ``CENSO_ESCOLAR_URL`` ou pelo argumento ``url=``.
URL_MICRODADOS = os.environ.get(
    ENV_URL,
    "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip",
)


def encontrar_raiz(inicio: Path | str | None = None) -> Path:
    """Sobe na árvore de diretórios até achar um marcador de raiz do projeto.

    A busca começa em ``inicio``; se omitido, começa no diretório deste módulo,
    o que funciona mesmo com o pacote importado a partir de um cwd arbitrário.
    """
    env = os.environ.get(ENV_RAIZ)
    if env:
        return Path(env).expanduser().resolve()

    atual = Path(inicio).resolve() if inicio else Path(__file__).resolve().parent
    for candidato in (atual, *atual.parents):
        if any((candidato / marcador).exists() for marcador in _MARCADORES_RAIZ):
            return candidato
    # Instalado como wheel, fora do repositório: cai no cwd.
    return Path.cwd().resolve()


@dataclass(frozen=True)
class Paths:
    """Diretórios do projeto, já resolvidos em caminhos absolutos."""

    raiz: Path
    data: Path
    raw: Path
    interim: Path
    processed: Path
    notebooks: Path
    reports: Path
    figures: Path

    def criar(self) -> Paths:
        """Cria os diretórios de dados e de saída que ainda não existem."""
        for p in (self.raw, self.interim, self.processed, self.figures):
            p.mkdir(parents=True, exist_ok=True)
        return self


def get_paths(raiz: Path | str | None = None) -> Paths:
    """Devolve os caminhos padrão do projeto."""
    root = Path(raiz).expanduser().resolve() if raiz else encontrar_raiz()
    if ENV_DATA in os.environ:
        data = Path(os.environ[ENV_DATA]).expanduser().resolve()
    else:
        data = root / "data"
    reports = root / "reports"
    return Paths(
        raiz=root,
        data=data,
        raw=data / "raw",
        interim=data / "interim",
        processed=data / "processed",
        notebooks=root / "notebooks",
        reports=reports,
        figures=reports / "figures",
    )
