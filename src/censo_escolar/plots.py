"""Gráficos para exploração no Jupyter ou para gravar em arquivo.

No Jupyter uma figura aparece sozinha (``%matplotlib inline``); rodando sem
interface — CI, script, ``nbconvert``, relatório — não há para onde a figura
"aparecer", então é preciso **gravar um arquivo**.

A solução aqui é toda função de plot aceitar ``arquivo=`` e devolver o caminho
gravado (ou o ``Axes``, se ``arquivo`` for ``None``). No notebook, ignore o
retorno e veja a figura; para gerar um PNG, passe ``arquivo=``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

from censo_escolar.config import get_paths

#: Paleta categórica sóbria, legível em tema claro e escuro.
PALETA = ("#4269d0", "#efb118", "#ff725c", "#6cc5b0", "#3ca951", "#a463f2", "#97bbf5")


def aplicar_estilo() -> None:
    """Aplica um estilo enxuto ao matplotlib. Chame uma vez por sessão."""
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.figsize": (9, 5),
            "figure.dpi": 110,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.alpha": 0.25,
            "axes.prop_cycle": matplotlib.cycler(color=list(PALETA)),
            "font.size": 10,
        }
    )


def _finalizar(ax, arquivo: str | Path | None):
    """Grava a figura se ``arquivo`` foi dado; senão devolve o ``Axes``."""
    if arquivo is None:
        return ax
    caminho = Path(arquivo)
    if not caminho.is_absolute():
        caminho = get_paths().figures / caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    ax.figure.savefig(caminho)
    # Fecha para não acumular figuras abertas entre execuções.
    ax.figure.clf()
    return str(caminho)


def barras(
    df: pd.DataFrame,
    x: str,
    y: str,
    *,
    titulo: str = "",
    rotulo_y: str = "",
    horizontal: bool = False,
    arquivo: str | Path | None = None,
):
    """Gráfico de barras a partir de duas colunas de um DataFrame."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    if horizontal:
        dados = df.iloc[::-1]
        ax.barh(dados[x].astype(str), dados[y], color=PALETA[0])
        ax.set_xlabel(rotulo_y or y)
        ax.grid(axis="x", alpha=0.25)
        ax.grid(axis="y", visible=False)
    else:
        ax.bar(df[x].astype(str), df[y], color=PALETA[0])
        ax.set_ylabel(rotulo_y or y)
        if len(df) > 8:
            ax.tick_params(axis="x", rotation=90)
    ax.set_title(titulo)
    return _finalizar(ax, arquivo)


def linhas(
    df: pd.DataFrame,
    x: str,
    y: str,
    *,
    serie: str | None = None,
    titulo: str = "",
    rotulo_y: str = "",
    arquivo: str | Path | None = None,
):
    """Série temporal; com ``serie``, uma linha por valor dessa coluna."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    if serie is None:
        ax.plot(df[x], df[y], marker="o")
    else:
        for i, (nome, grupo) in enumerate(df.groupby(serie, observed=True)):
            ax.plot(grupo[x], grupo[y], marker="o", label=str(nome), color=PALETA[i % len(PALETA)])
        ax.legend(frameon=False, ncols=2)
    ax.set_xlabel(x)
    ax.set_ylabel(rotulo_y or y)
    ax.set_title(titulo)
    return _finalizar(ax, arquivo)
