"""Análise dos microdados do Censo Escolar da Educação Básica (INEP).

A regra de ouro do projeto: *toda* lógica de verdade mora aqui, no pacote. Os
documentos em ``notebooks/`` (``.org`` e ``.ipynb``) são só narrativa mais
chamadas a estas funções. É isso que torna a mesma base de código utilizável
tanto no org-babel do Emacs quanto no Jupyter.
"""

from censo_escolar.analysis import (
    contar_escolas,
    distribuicao_dependencia,
    maiores_municipios,
    panorama_por_uf,
    serie_historica,
    somar_matriculas,
    taxa_infraestrutura,
)
from censo_escolar.codigos import adicionar_regiao, rotular
from censo_escolar.config import Paths, get_paths
from censo_escolar.loading import (
    COLUNAS_BASICAS,
    COLUNAS_INFRA,
    COLUNAS_QUANTITATIVAS,
    carregar_anos,
    carregar_escolas,
    colunas_disponiveis,
    converter_para_parquet,
    localizar_csv_escolas,
)

__all__ = [
    "COLUNAS_BASICAS",
    "COLUNAS_INFRA",
    "COLUNAS_QUANTITATIVAS",
    "Paths",
    "adicionar_regiao",
    "carregar_anos",
    "carregar_escolas",
    "colunas_disponiveis",
    "contar_escolas",
    "converter_para_parquet",
    "distribuicao_dependencia",
    "get_paths",
    "localizar_csv_escolas",
    "maiores_municipios",
    "panorama_por_uf",
    "rotular",
    "serie_historica",
    "somar_matriculas",
    "taxa_infraestrutura",
]
__version__ = "0.1.0"
