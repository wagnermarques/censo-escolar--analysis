"""Análise dos microdados do Censo Escolar da Educação Básica (INEP).

A regra de ouro do projeto: *toda* lógica de verdade mora aqui, no pacote. Os
documentos em ``notebooks/`` são só narrativa mais chamadas a estas funções.
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
from censo_escolar.esquema import (
    anos_disponiveis,
    carregar_dicionario,
    colunas_comuns,
    contagem_por_ano,
    dicionario_de_dados,
    dtypes_para_serie_historica,
    ler_dicionario_inep,
    matriz_presenca,
    perfilar,
    perfilar_anos,
    resumo_presenca,
    salvar_dicionario,
    tipos_por_ano,
)
from censo_escolar.inventario import Microdados, inventariar
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
    "Microdados",
    "Paths",
    "adicionar_regiao",
    "anos_disponiveis",
    "carregar_anos",
    "carregar_dicionario",
    "carregar_escolas",
    "colunas_comuns",
    "colunas_disponiveis",
    "contagem_por_ano",
    "contar_escolas",
    "converter_para_parquet",
    "dicionario_de_dados",
    "distribuicao_dependencia",
    "dtypes_para_serie_historica",
    "get_paths",
    "inventariar",
    "ler_dicionario_inep",
    "localizar_csv_escolas",
    "maiores_municipios",
    "matriz_presenca",
    "panorama_por_uf",
    "perfilar",
    "perfilar_anos",
    "resumo_presenca",
    "rotular",
    "salvar_dicionario",
    "serie_historica",
    "somar_matriculas",
    "taxa_infraestrutura",
    "tipos_por_ano",
]
__version__ = "0.1.0"
