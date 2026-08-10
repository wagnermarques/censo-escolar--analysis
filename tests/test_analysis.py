"""Testes das agregações, com um DataFrame sintético no formato do Censo."""

from __future__ import annotations

import pandas as pd
import pytest

from censo_escolar import analysis
from censo_escolar.codigos import adicionar_regiao, rotular


@pytest.fixture
def escolas() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "NU_ANO_CENSO": [2023] * 6,
            "CO_ENTIDADE": [1, 2, 3, 4, 5, 6],
            "SG_UF": ["MG", "MG", "MG", "SP", "SP", "BA"],
            "CO_MUNICIPIO": [3106200, 3106200, 3170206, 3550308, 3550308, 2927408],
            "NO_MUNICIPIO": [
                "Belo Horizonte",
                "Belo Horizonte",
                "Uberlândia",
                "São Paulo",
                "São Paulo",
                "Salvador",
            ],
            "TP_DEPENDENCIA": [3, 2, 4, 2, 4, 3],
            "TP_LOCALIZACAO": [1, 1, 1, 1, 2, 1],
            "QT_MAT_BAS": pd.array([500, 300, 250, 900, 120, 400], dtype="Int32"),
            "QT_DOC_BAS": pd.array([30, 20, 15, 60, 10, 25], dtype="Int32"),
            "IN_INTERNET": pd.array([1, 1, 1, 1, 0, pd.NA], dtype="Int8"),
            "IN_BIBLIOTECA": pd.array([0, 1, 1, 1, 0, 0], dtype="Int8"),
        }
    )


def test_contar_escolas(escolas):
    out = analysis.contar_escolas(escolas, "SG_UF", normalizar=True)
    assert out.loc[out.SG_UF == "MG", "escolas"].item() == 3
    assert out["pct"].sum() == pytest.approx(1.0)


def test_somar_matriculas(escolas):
    out = analysis.somar_matriculas(escolas, "SG_UF")
    assert out.loc[out.SG_UF == "SP", "QT_MAT_BAS"].item() == 1020


def test_taxa_infraestrutura_nacional_ignora_nulos(escolas):
    out = analysis.taxa_infraestrutura(escolas).set_index("indicador")["taxa"]
    # IN_INTERNET: 4 de 5 não nulos.
    assert out["IN_INTERNET"] == pytest.approx(0.8)
    assert out["IN_BIBLIOTECA"] == pytest.approx(3 / 6)


def test_taxa_infraestrutura_por_grupo(escolas):
    out = analysis.taxa_infraestrutura(escolas, por="SG_UF")
    assert set(out["SG_UF"]) == {"MG", "SP", "BA"}
    assert out.loc[out.SG_UF == "MG", "IN_INTERNET"].item() == pytest.approx(1.0)


def test_taxa_infraestrutura_sem_colunas_in():
    with pytest.raises(KeyError):
        analysis.taxa_infraestrutura(pd.DataFrame({"SG_UF": ["MG"]}))


def test_panorama_por_uf(escolas):
    out = analysis.panorama_por_uf(escolas)
    linha = out[out.SG_UF == "MG"].iloc[0]
    assert linha["escolas"] == 3
    assert linha["matriculas"] == 1050
    assert linha["regiao"] == "Sudeste"
    assert linha["matriculas_por_escola"] == pytest.approx(350.0)


def test_panorama_sem_sg_uf():
    with pytest.raises(KeyError):
        analysis.panorama_por_uf(pd.DataFrame({"QT_MAT_BAS": [1]}))


def test_distribuicao_dependencia(escolas):
    total = analysis.distribuicao_dependencia(escolas)
    assert set(total["DS_DEPENDENCIA"]) == {"Estadual", "Municipal", "Privada"}
    assert total["pct"].sum() == pytest.approx(1.0)

    por_uf = analysis.distribuicao_dependencia(escolas, por="SG_UF")
    assert "SG_UF" in por_uf.columns


def test_maiores_municipios(escolas):
    out = analysis.maiores_municipios(escolas, n=2)
    assert list(out["NO_MUNICIPIO"]) == ["São Paulo", "Belo Horizonte"]
    assert out.iloc[0]["escolas"] == 2


def test_serie_historica():
    df = pd.DataFrame(
        {
            "NU_ANO_CENSO": [2021, 2021, 2023, 2023],
            "SG_UF": ["MG", "SP", "MG", "SP"],
            "QT_MAT_BAS": [10, 20, 15, 25],
        }
    )
    out = analysis.serie_historica(df, por="SG_UF")
    assert len(out) == 4
    assert out.loc[(out.NU_ANO_CENSO == 2023) & (out.SG_UF == "MG"), "QT_MAT_BAS"].item() == 15

    nacional = analysis.serie_historica(df)
    assert list(nacional["QT_MAT_BAS"]) == [30, 40]


def test_rotular_preserva_a_coluna_original(escolas):
    out = rotular(escolas, "TP_DEPENDENCIA")
    assert "TP_DEPENDENCIA" in out.columns
    assert out.loc[0, "DS_DEPENDENCIA"] == "Municipal"


def test_rotular_todas_por_padrao(escolas):
    out = rotular(escolas)
    assert {"DS_DEPENDENCIA", "DS_LOCALIZACAO"} <= set(out.columns)


def test_rotular_coluna_ausente(escolas):
    with pytest.raises(KeyError):
        rotular(escolas, "TP_INEXISTENTE")


def test_adicionar_regiao(escolas):
    out = adicionar_regiao(escolas)
    assert out.loc[out.SG_UF == "BA", "NO_REGIAO"].iloc[0] == "Nordeste"
