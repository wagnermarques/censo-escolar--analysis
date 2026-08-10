"""Agregações reutilizáveis sobre o arquivo de escolas.

Todas as funções recebem e devolvem ``DataFrame``, sem imprimir nem plotar
nada. É essa disciplina que permite chamá-las de um bloco org-babel, de uma
célula Jupyter, de um teste ou de um script, sem adaptação.
"""

from __future__ import annotations

import pandas as pd

from censo_escolar.codigos import UF_PARA_REGIAO, rotular


def contar_escolas(
    df: pd.DataFrame,
    por: str | list[str],
    *,
    normalizar: bool = False,
) -> pd.DataFrame:
    """Conta escolas agrupando por uma ou mais colunas.

    :param normalizar: acrescenta a coluna ``pct`` com a participação de cada
        grupo no total.
    """
    chaves = [por] if isinstance(por, str) else list(por)
    out = df.groupby(chaves, observed=True).size().reset_index(name="escolas")
    if normalizar:
        out["pct"] = out["escolas"] / out["escolas"].sum()
    return out.sort_values("escolas", ascending=False, ignore_index=True)


def somar_matriculas(
    df: pd.DataFrame,
    por: str | list[str],
    *,
    colunas: list[str] | None = None,
) -> pd.DataFrame:
    """Soma as colunas ``QT_MAT_*`` por grupo.

    :param colunas: quais colunas somar. Por padrão, todas as ``QT_MAT_*``
        presentes no DataFrame.
    """
    chaves = [por] if isinstance(por, str) else list(por)
    alvo = colunas if colunas is not None else [c for c in df.columns if c.startswith("QT_MAT_")]
    if not alvo:
        raise KeyError("nenhuma coluna QT_MAT_* no DataFrame — inclua-as em carregar_escolas()")
    out = df.groupby(chaves, observed=True)[alvo].sum(min_count=1).reset_index()
    return out


def taxa_infraestrutura(
    df: pd.DataFrame,
    por: str | list[str] | None = None,
    *,
    indicadores: list[str] | None = None,
) -> pd.DataFrame:
    """Proporção de escolas que possuem cada item de infraestrutura.

    As colunas ``IN_*`` do Censo são binárias (0/1) com vazio para "não
    aplicável"; a média ignora os vazios, então o resultado é a fração entre as
    escolas para as quais o item faz sentido.

    Sem ``por``, devolve uma linha por indicador (visão nacional). Com ``por``,
    devolve uma linha por grupo e uma coluna por indicador.
    """
    if indicadores is not None:
        alvo = indicadores
    else:
        alvo = [c for c in df.columns if c.startswith("IN_")]
    if not alvo:
        raise KeyError(
            "nenhuma coluna IN_* no DataFrame — inclua COLUNAS_INFRA em carregar_escolas()"
        )

    if por is None:
        taxas = df[alvo].astype("Float64").mean()
        return (
            taxas.rename("taxa")
            .rename_axis("indicador")
            .reset_index()
            .sort_values("taxa", ascending=False, ignore_index=True)
        )

    chaves = [por] if isinstance(por, str) else list(por)
    return (
        df.groupby(chaves, observed=True)[alvo]
        .apply(lambda g: g.astype("Float64").mean())
        .reset_index()
    )


def panorama_por_uf(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por UF: escolas, matrículas, docentes e média de matrículas.

    Exige ``SG_UF``; usa ``QT_MAT_BAS`` e ``QT_DOC_BAS`` quando presentes.
    """
    if "SG_UF" not in df.columns:
        raise KeyError("panorama_por_uf exige a coluna SG_UF")

    agregacoes: dict[str, tuple[str, str]] = {"escolas": ("SG_UF", "size")}
    if "QT_MAT_BAS" in df.columns:
        agregacoes["matriculas"] = ("QT_MAT_BAS", "sum")
    if "QT_DOC_BAS" in df.columns:
        agregacoes["docentes"] = ("QT_DOC_BAS", "sum")

    out = df.groupby("SG_UF", observed=True).agg(**agregacoes).reset_index()
    out["regiao"] = out["SG_UF"].map(UF_PARA_REGIAO)
    if "matriculas" in out.columns:
        out["matriculas_por_escola"] = out["matriculas"] / out["escolas"]
    return out.sort_values("escolas", ascending=False, ignore_index=True)


def distribuicao_dependencia(df: pd.DataFrame, por: str | None = None) -> pd.DataFrame:
    """Distribuição de escolas por dependência administrativa.

    Com ``por`` (tipicamente ``"SG_UF"``), devolve uma tabela cruzada com a
    participação percentual de cada rede dentro de cada grupo.
    """
    rotulado = rotular(df, "TP_DEPENDENCIA")
    if por is None:
        return contar_escolas(rotulado, "DS_DEPENDENCIA", normalizar=True)

    tabela = pd.crosstab(rotulado[por], rotulado["DS_DEPENDENCIA"], normalize="index")
    return tabela.reset_index()


def serie_historica(
    df: pd.DataFrame,
    metrica: str = "QT_MAT_BAS",
    *,
    por: str | None = None,
) -> pd.DataFrame:
    """Evolução anual de uma métrica somada, opcionalmente quebrada por grupo.

    Espera um DataFrame com vários anos (veja
    :func:`censo_escolar.loading.carregar_anos`).
    """
    if "NU_ANO_CENSO" not in df.columns:
        raise KeyError("serie_historica exige a coluna NU_ANO_CENSO")
    chaves = ["NU_ANO_CENSO"] + ([por] if por else [])
    out = df.groupby(chaves, observed=True)[metrica].sum(min_count=1).reset_index()
    return out.sort_values(chaves, ignore_index=True)


def maiores_municipios(df: pd.DataFrame, n: int = 20, metrica: str = "QT_MAT_BAS") -> pd.DataFrame:
    """Os ``n`` municípios com maior valor somado de ``metrica``."""
    chaves = [c for c in ("SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO") if c in df.columns]
    if not chaves:
        raise KeyError("é preciso ao menos NO_MUNICIPIO ou CO_MUNICIPIO no DataFrame")
    out = (
        df.groupby(chaves, observed=True)
        .agg(escolas=("CO_ENTIDADE", "size"), total=(metrica, "sum"))
        .reset_index()
    )
    return out.nlargest(n, "total").reset_index(drop=True)
