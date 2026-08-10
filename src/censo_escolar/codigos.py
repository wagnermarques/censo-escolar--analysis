"""Dicionários de códigos do Censo Escolar.

Os microdados vêm quase todos codificados numericamente. Estes mapas cobrem as
variáveis categóricas mais usadas do arquivo de escolas. Para o dicionário
completo, veja a planilha em ``anexos/`` dentro do ZIP do INEP.
"""

from __future__ import annotations

import pandas as pd

TP_DEPENDENCIA = {
    1: "Federal",
    2: "Estadual",
    3: "Municipal",
    4: "Privada",
}

TP_LOCALIZACAO = {
    1: "Urbana",
    2: "Rural",
}

TP_LOCALIZACAO_DIFERENCIADA = {
    0: "Não está em área diferenciada",
    1: "Área de assentamento",
    2: "Terra indígena",
    3: "Área remanescente de quilombos",
    # Códigos 7/8 aparecem em anos mais recentes com redação revisada.
    7: "Área de assentamento",
    8: "Terra indígena",
}

TP_SITUACAO_FUNCIONAMENTO = {
    1: "Em atividade",
    2: "Paralisada",
    3: "Extinta (ano do censo)",
    4: "Extinta em anos anteriores",
}

TP_CATEGORIA_ESCOLA_PRIVADA = {
    1: "Particular",
    2: "Comunitária",
    3: "Confessional",
    4: "Filantrópica",
}

#: Sigla da UF -> (código IBGE, nome, região)
UFS: dict[str, tuple[int, str, str]] = {
    "RO": (11, "Rondônia", "Norte"),
    "AC": (12, "Acre", "Norte"),
    "AM": (13, "Amazonas", "Norte"),
    "RR": (14, "Roraima", "Norte"),
    "PA": (15, "Pará", "Norte"),
    "AP": (16, "Amapá", "Norte"),
    "TO": (17, "Tocantins", "Norte"),
    "MA": (21, "Maranhão", "Nordeste"),
    "PI": (22, "Piauí", "Nordeste"),
    "CE": (23, "Ceará", "Nordeste"),
    "RN": (24, "Rio Grande do Norte", "Nordeste"),
    "PB": (25, "Paraíba", "Nordeste"),
    "PE": (26, "Pernambuco", "Nordeste"),
    "AL": (27, "Alagoas", "Nordeste"),
    "SE": (28, "Sergipe", "Nordeste"),
    "BA": (29, "Bahia", "Nordeste"),
    "MG": (31, "Minas Gerais", "Sudeste"),
    "ES": (32, "Espírito Santo", "Sudeste"),
    "RJ": (33, "Rio de Janeiro", "Sudeste"),
    "SP": (35, "São Paulo", "Sudeste"),
    "PR": (41, "Paraná", "Sul"),
    "SC": (42, "Santa Catarina", "Sul"),
    "RS": (43, "Rio Grande do Sul", "Sul"),
    "MS": (50, "Mato Grosso do Sul", "Centro-Oeste"),
    "MT": (51, "Mato Grosso", "Centro-Oeste"),
    "GO": (52, "Goiás", "Centro-Oeste"),
    "DF": (53, "Distrito Federal", "Centro-Oeste"),
}

#: Código IBGE da UF -> sigla
CO_UF_PARA_SIGLA: dict[int, str] = {codigo: sigla for sigla, (codigo, _, _) in UFS.items()}

#: Sigla da UF -> região
UF_PARA_REGIAO: dict[str, str] = {sigla: regiao for sigla, (_, _, regiao) in UFS.items()}

#: Mapa de coluna -> dicionário de rótulos, consultado por :func:`rotular`.
MAPAS: dict[str, dict[int, str]] = {
    "TP_DEPENDENCIA": TP_DEPENDENCIA,
    "TP_LOCALIZACAO": TP_LOCALIZACAO,
    "TP_LOCALIZACAO_DIFERENCIADA": TP_LOCALIZACAO_DIFERENCIADA,
    "TP_SITUACAO_FUNCIONAMENTO": TP_SITUACAO_FUNCIONAMENTO,
    "TP_CATEGORIA_ESCOLA_PRIVADA": TP_CATEGORIA_ESCOLA_PRIVADA,
}


def rotular(df: pd.DataFrame, colunas: str | list[str] | None = None) -> pd.DataFrame:
    """Devolve uma cópia de ``df`` com as colunas ``TP_*`` traduzidas em texto.

    Cria colunas novas com o prefixo ``DS_`` (descrição) em vez de sobrescrever
    as originais, para que os códigos continuem disponíveis para agrupamentos e
    junções.

    :param colunas: colunas a traduzir. Por padrão, todas as de :data:`MAPAS`
        presentes no DataFrame.
    """
    if isinstance(colunas, str):
        colunas = [colunas]
    alvo = colunas if colunas is not None else [c for c in MAPAS if c in df.columns]

    out = df.copy()
    for coluna in alvo:
        if coluna not in out.columns:
            raise KeyError(f"coluna ausente no DataFrame: {coluna}")
        if coluna not in MAPAS:
            raise KeyError(f"sem mapa de códigos para: {coluna}")
        destino = "DS_" + coluna.removeprefix("TP_")
        out[destino] = out[coluna].map(MAPAS[coluna]).astype("category")
    return out


def adicionar_regiao(df: pd.DataFrame, coluna_uf: str = "SG_UF") -> pd.DataFrame:
    """Acrescenta a coluna ``NO_REGIAO`` a partir da sigla da UF."""
    out = df.copy()
    out["NO_REGIAO"] = out[coluna_uf].map(UF_PARA_REGIAO).astype("category")
    return out
