"""Recorte visualizável dos microdados: poucas linhas num arquivo que abre inteiro.

O CSV de escolas tem ~215 mil linhas e ~370 colunas; a tabela de matrículas de
2025 é bem maior. Abrir isso no Calc ou no Excel não é uma questão de
paciência: o Calc carrega a planilha inteira em memória antes de desenhar a
primeira célula, e numa máquina modesta ele engasga antes de mostrar qualquer
coisa — ou mostra, e aí cada busca varre tudo de novo.

Nenhum dos dois programas sabe importar "só as N primeiras linhas" (o diálogo
do Calc tem *a partir de* que linha começar, não quantas ler). Então o corte
precisa acontecer antes, e é o que este módulo faz: lê o CSV em blocos, para no
instante em que junta as linhas pedidas e grava um arquivo pequeno.

Por isso a memória usada não depende do tamanho do arquivo de origem — depende
do bloco (:data:`TAMANHO_BLOCO`) e do tanto que foi pedido.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

from censo_escolar.config import ENCODING, SEPARADOR, Paths, get_paths
from censo_escolar.loading import localizar_csv_escolas

#: Quantas linhas o recorte traz quando ninguém diz o contrário. Cabe numa tela
#: de rolagem e abre instantaneamente em qualquer máquina.
LINHAS_PADRAO = 100

#: Linhas lidas por vez do CSV. É este número, e não o tamanho do arquivo, que
#: determina o pico de memória da amostragem.
TAMANHO_BLOCO = 20_000

#: Largura máxima de coluna no .xlsx, em caracteres. ``NO_ENTIDADE`` tem nomes
#: de escola longuíssimos, e uma coluna de 120 caracteres empurra todo o resto
#: para fora da tela.
LARGURA_MAX_COLUNA = 40


class SemLinhas(LookupError):
    """Nenhuma linha sobreviveu aos filtros pedidos."""


def pares_de_filtro(itens: list[str] | None, rotulo: str) -> dict[str, str]:
    """``["SG_UF=MG"]`` vira ``{"SG_UF": "MG"}``.

    Só o primeiro ``=`` separa: o valor pode conter outros, e há colunas do INEP
    cujo conteúdo é texto livre.
    """
    pares: dict[str, str] = {}
    for item in itens or []:
        if "=" not in item:
            raise ValueError(f"--{rotulo} espera COLUNA=VALOR, recebi {item!r}")
        coluna, valor = item.split("=", 1)
        pares[coluna.strip().upper()] = valor.strip()
    return pares


def _cabecalho(csv: Path) -> list[str]:
    return list(pd.read_csv(csv, sep=SEPARADOR, encoding=ENCODING, nrows=0).columns)


def localizar_origem(
    ano: int | None = None,
    *,
    arquivo: Path | None = None,
    paths: Paths | None = None,
) -> Path:
    """O CSV de onde a amostra sai: um caminho explícito ou o de escolas do ano."""
    if arquivo is not None:
        caminho = Path(arquivo).expanduser()
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
        return caminho
    if ano is None:
        raise ValueError("informe o ano ou --arquivo")
    return localizar_csv_escolas(ano, paths=paths)


def amostrar(
    ano: int | None = None,
    *,
    arquivo: Path | None = None,
    linhas: int = LINHAS_PADRAO,
    colunas: list[str] | None = None,
    onde: dict[str, str] | None = None,
    contem: dict[str, str] | None = None,
    paths: Paths | None = None,
) -> tuple[pd.DataFrame, Path, int]:
    """Lê o começo do CSV — ou as primeiras linhas que casam com os filtros.

    :param linhas: quantas linhas trazer.
    :param colunas: recorte de colunas; as inexistentes no arquivo são
        ignoradas, como no resto do projeto (o INEP renomeia variáveis).
    :param onde: igualdade exata, sem diferenciar maiúsculas (``SG_UF=mg``).
    :param contem: o valor aparece em qualquer parte do texto da célula.
    :returns: ``(recorte, arquivo_de_origem, linhas_lidas)`` — o terceiro item
        é quanto do arquivo precisou ser varrido, que é o que separa "achei nas
        primeiras linhas" de "varri o arquivo inteiro e era só isso".

    Tudo é lido como texto. Um recorte para *conferir* o dado não pode
    reinterpretá-lo pelo caminho: ``0MI11`` em ``CO_ORGAO_REGIONAL`` e os zeros
    à esquerda dos códigos do IBGE são exatamente o tipo de coisa que se abre a
    planilha para ver.
    """
    origem = localizar_origem(ano, arquivo=arquivo, paths=paths)
    onde = onde or {}
    contem = contem or {}

    disponiveis = _cabecalho(origem)
    desconhecidas = [c for c in (*onde, *contem) if c not in disponiveis]
    if desconhecidas:
        raise KeyError(
            f"Coluna(s) inexistente(s) em {origem.name}: {', '.join(desconhecidas)}.\n"
            f"Veja as colunas com: censo colunas <ano>"
        )

    if colunas:
        pedidas = [c.strip().upper() for c in colunas]
        # As colunas filtradas entram mesmo sem terem sido pedidas: esconder a
        # coluna que motivou o recorte deixaria o resultado impossível de
        # conferir a olho.
        efetivas = [c for c in disponiveis if c in {*pedidas, *onde, *contem}]
        if not efetivas:
            raise KeyError(f"Nenhuma das colunas pedidas existe em {origem.name}")
    else:
        efetivas = disponiveis

    blocos: list[pd.DataFrame] = []
    faltam = linhas
    lidas = 0
    leitor = pd.read_csv(
        origem,
        sep=SEPARADOR,
        encoding=ENCODING,
        usecols=efetivas,
        dtype="string",
        chunksize=TAMANHO_BLOCO,
    )
    with leitor:
        for bloco in leitor:
            lidas += len(bloco)
            bloco = _filtrar(bloco[efetivas], onde, contem)
            if not bloco.empty:
                blocos.append(bloco.head(faltam))
                faltam -= len(blocos[-1])
            # Sair aqui é a razão de o comando responder em um segundo no caso
            # comum: as primeiras linhas do arquivo bastam, e o resto dos
            # megabytes nunca é tocado.
            if faltam <= 0:
                break

    if not blocos:
        raise SemLinhas(
            f"Nenhuma linha de {origem.name} casa com os filtros "
            f"({lidas} linhas varridas)."
        )
    return pd.concat(blocos, ignore_index=True), origem, lidas


def _filtrar(bloco: pd.DataFrame, onde: dict[str, str], contem: dict[str, str]) -> pd.DataFrame:
    for coluna, valor in onde.items():
        bloco = bloco[bloco[coluna].str.strip().str.casefold() == valor.casefold()]
    for coluna, texto in contem.items():
        bloco = bloco[bloco[coluna].str.contains(texto, case=False, na=False, regex=False)]
    return bloco


def caminho_amostra(origem: Path, *, paths: Paths | None = None, formato: str = "xlsx") -> Path:
    """Onde a amostra é gravada quando ninguém escolhe o destino."""
    return (paths or get_paths()).processed / f"amostra_{origem.stem}.{formato}"


def salvar(df: pd.DataFrame, destino: Path) -> Path:
    """Grava o recorte. A extensão decide o formato: ``.xlsx`` ou ``.csv``."""
    destino = Path(destino).expanduser()
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.suffix.lower() == ".csv":
        # utf-8-sig: o BOM é o que faz o Calc e o Excel acertarem o encoding
        # sozinhos. Sem ele, o acento de "Educação" vira sujeira até alguém
        # descobrir o diálogo de importação.
        df.to_csv(destino, sep=SEPARADOR, index=False, encoding="utf-8-sig")
        return destino
    _salvar_xlsx(df, destino)
    return destino


def _salvar_xlsx(df: pd.DataFrame, destino: Path) -> None:
    """Escreve o .xlsx já arrumado para leitura: cabeçalho fixo e filtro ligado.

    O .xlsx existe aqui por ser o formato que abre com dois cliques, sem
    diálogo de importação — nada de escolher encoding, separador ou tipo de
    coluna, que é justamente o passo em que o CSV do INEP costuma ser lido
    errado. O Calc abre igual ao Excel.
    """
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    quadro = _numeros_onde_der(df)
    with pd.ExcelWriter(destino, engine="openpyxl") as escritor:
        quadro.to_excel(escritor, index=False, sheet_name="amostra")
        planilha = escritor.sheets["amostra"]
        for celula in planilha[1]:
            celula.font = Font(bold=True)
        # Cabeçalho congelado e AutoFiltro: com ~370 colunas, rolar sem o
        # cabeçalho à vista é perder de vista o que se está lendo, e o filtro
        # do cabeçalho é a busca visual que o usuário quer.
        planilha.freeze_panes = "A2"
        planilha.auto_filter.ref = planilha.dimensions
        for i, coluna in enumerate(quadro.columns, start=1):
            conteudo = quadro[coluna].astype("string").fillna("")
            largura = max(len(str(coluna)), int(conteudo.str.len().max() or 0)) + 2
            planilha.column_dimensions[get_column_letter(i)].width = min(
                largura, LARGURA_MAX_COLUNA
            )


def _numeros_onde_der(df: pd.DataFrame) -> pd.DataFrame:
    """Converte para número as colunas em que isso não perde informação.

    Colunas numéricas viram número para poderem ser somadas e ordenadas na
    planilha. Ficam de fora as que têm zero à esquerda: ``00009`` e ``9`` são o
    mesmo número e códigos diferentes — a mesma regra que ``esquema.py`` usa
    para decidir que uma coluna é identificador, não quantidade.
    """
    quadro = df.copy()
    for coluna in quadro.columns:
        valores = quadro[coluna].dropna()
        if valores.empty:
            continue
        if (valores.str.len() > 1).any() and valores.str.match(r"^0[^.,]").any():
            continue
        numeros = pd.to_numeric(valores.str.replace(",", ".", regex=False), errors="coerce")
        if numeros.notna().all():
            quadro[coluna] = pd.to_numeric(
                quadro[coluna].str.replace(",", ".", regex=False), errors="coerce"
            )
    return quadro


def abrir_no_sistema(caminho: Path) -> None:
    """Entrega o arquivo ao programa padrão do sistema (Calc, Excel, o que houver)."""
    if sys.platform.startswith("win"):
        import os

        os.startfile(caminho)  # type: ignore[attr-defined]  # noqa: S606
        return
    programa = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([programa, str(caminho)], check=False)
