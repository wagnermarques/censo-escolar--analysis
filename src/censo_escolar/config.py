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

#: Sobrepõe o bundle de CAs usado na verificação TLS do download.
ENV_CA_BUNDLE = "CENSO_ESCOLAR_CA_BUNDLE"

#: Encoding e separador usados pelo INEP nos CSVs de microdados.
ENCODING = "latin-1"
SEPARADOR = ";"

#: Padrões de URL dos microdados, tentados em ordem até um responder.
#:
#: São vários pelo mesmo motivo de ``_PADROES_ESCOLAS`` em ``loading.py``: o
#: INEP não é consistente no nome do arquivo. O pacote de 2025 foi publicado
#: como ``microdados_censo_escolar_2025_.zip`` — com um sublinhado sobrando
#: antes da extensão —, então o padrão de sempre devolve 404 para um ano que
#: existe. Um erro difícil de diagnosticar de fora, porque a página do INEP
#: lista o ano normalmente.
#:
#: Confira em https://www.gov.br/inep/ (Dados Abertos > Microdados) e, se
#: aparecer uma variante nova, acrescente aqui.
PADROES_URL: tuple[str, ...] = (
    "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip",
    "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}_.zip",
)

#: Primeiro padrão, ou a sobreposição via ``CENSO_ESCOLAR_URL``. Uma
#: sobreposição explícita desliga a busca pelas variantes: quem aponta para
#: outro endereço quer aquele endereço, não um palpite em cima dele.
URL_MICRODADOS = os.environ.get(ENV_URL, PADROES_URL[0])

#: O servidor do INEP envia só o certificado folha, sem a CA intermediária que
#: o encadeia até a raiz GlobalSign (já confiável). Sem esse intermediário a
#: verificação falha com "unable to get local issuer certificate". A URL sai do
#: campo "CA Issuers" (AIA) do próprio certificado do INEP; se um dia o
#: certificado for reemitido por outra CA, atualize aqui — ou aponte
#: ``CENSO_ESCOLAR_CA_BUNDLE`` para um bundle pronto.
URL_CA_INTERMEDIARIA = "http://secure.globalsign.com/cacert/rnpicpedugr46ovtlsca2025.crt"


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
    certs: Path

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
        certs=root / "certs",
    )
