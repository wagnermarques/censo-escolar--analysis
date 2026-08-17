"""Testes dos gráficos.

O ponto sob teste é o contrato duplo: sem ``arquivo`` devolve o ``Axes`` (modo
Jupyter); com ``arquivo`` grava o PNG e devolve o caminho (modo headless).
"""

from __future__ import annotations

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

from censo_escolar import plots  # noqa: E402


@pytest.fixture
def dados() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "SG_UF": ["MG", "SP", "BA"],
            "escolas": [3, 2, 1],
            "ano": [2021, 2022, 2023],
        }
    )


def test_barras_sem_arquivo_devolve_axes(dados):
    ax = plots.barras(dados, x="SG_UF", y="escolas")
    assert hasattr(ax, "figure")


def test_barras_com_arquivo_grava_e_devolve_caminho(dados, tmp_path):
    destino = tmp_path / "fig.png"
    devolvido = plots.barras(dados, x="SG_UF", y="escolas", arquivo=destino)
    assert devolvido == str(destino)
    assert destino.stat().st_size > 0


def test_caminho_relativo_vai_para_reports_figures(dados, tmp_path, monkeypatch):
    from censo_escolar import config

    monkeypatch.setenv(config.ENV_RAIZ, str(tmp_path))
    devolvido = plots.barras(dados, x="SG_UF", y="escolas", arquivo="fig.png")
    assert devolvido == str(tmp_path / "reports" / "figures" / "fig.png")


def test_barras_horizontal(dados, tmp_path):
    assert plots.barras(dados, x="SG_UF", y="escolas", horizontal=True, arquivo=tmp_path / "h.png")


def test_linhas_com_series(dados, tmp_path):
    df = pd.concat([dados.assign(rede="A"), dados.assign(rede="B", escolas=[1, 2, 3])])
    destino = tmp_path / "l.png"
    assert plots.linhas(df, x="ano", y="escolas", serie="rede", arquivo=destino) == str(destino)
    assert destino.exists()


def test_aplicar_estilo_nao_explode():
    plots.aplicar_estilo()
    import matplotlib.pyplot as plt

    assert plt.rcParams["axes.spines.top"] is False
