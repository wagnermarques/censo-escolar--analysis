"""Leitura dos CSVs de microdados e conversão para Parquet.

O arquivo de escolas do Censo Escolar tem ~370 colunas e ~215 mil linhas. Ler
tudo como ``object`` consome vários GiB; ler só as colunas necessárias, com
dtypes explícitos, resolve. E converter uma vez para Parquet torna as leituras
seguintes quase instantâneas — importante quando o mesmo dado é recarregado a
cada reinício de kernel, tanto no Jupyter quanto no org-babel.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd

from censo_escolar.config import ENCODING, SEPARADOR, Paths, get_paths

#: Nomes de arquivo do CSV de escolas, em ordem de preferência. O INEP mudou a
#: nomenclatura em 2019/2021 e de novo em 2025, quando o pacote passou a trazer
#: uma tabela por entidade (``Tabela_Escola_2025_V2.csv``, mais Matrícula,
#: Turma, Docente, Gestor e Curso Técnico) em vez de um único CSV de escolas —
#: daí o salto de ~30 MiB para ~512 MiB no ZIP.
#:
#: A âncora ``^...$`` importa: sem ela, ``Tabela_Gestor_Escolar_2025_v2.csv``
#: também casaria com o padrão de escola.
_PADROES_ESCOLAS = (
    r"^microdados_ed_basica_\d{4}\.csv$",
    r"^Tabela_Escola_\d{4}(_V\d+)?\.csv$",
    r"^ESCOLAS\.CSV$",
    r"^escolas\.csv$",
)

#: Conjunto enxuto de colunas que cobre a maior parte das análises de escolas.
#: Use :func:`colunas_disponiveis` para descobrir o resto.
COLUNAS_BASICAS: tuple[str, ...] = (
    "NU_ANO_CENSO",
    "CO_ENTIDADE",
    "NO_ENTIDADE",
    "CO_UF",
    "SG_UF",
    "CO_MUNICIPIO",
    "NO_MUNICIPIO",
    "TP_DEPENDENCIA",
    "TP_LOCALIZACAO",
    "TP_SITUACAO_FUNCIONAMENTO",
)

#: Indicadores de infraestrutura usados por padrão em análises de infra.
COLUNAS_INFRA: tuple[str, ...] = (
    "IN_AGUA_POTAVEL",
    "IN_ENERGIA_REDE_PUBLICA",
    "IN_ESGOTO_REDE_PUBLICA",
    "IN_BIBLIOTECA",
    "IN_LABORATORIO_INFORMATICA",
    "IN_LABORATORIO_CIENCIAS",
    "IN_QUADRA_ESPORTES",
    "IN_REFEITORIO",
    "IN_INTERNET",
    "IN_BANDA_LARGA",
    "IN_ACESSIBILIDADE_RAMPAS",
)

#: Contagens (matrículas, docentes, turmas) mais usadas.
COLUNAS_QUANTITATIVAS: tuple[str, ...] = (
    "QT_MAT_BAS",
    "QT_MAT_INF",
    "QT_MAT_FUND",
    "QT_MAT_MED",
    "QT_MAT_EJA",
    "QT_MAT_ESP",
    "QT_DOC_BAS",
    "QT_TUR_BAS",
    "QT_SALAS_UTILIZADAS",
)


def _dir_extraido(ano: int, paths: Paths) -> Path:
    destino = paths.interim / f"microdados_censo_escolar_{ano}"
    if not destino.exists():
        raise FileNotFoundError(
            f"Microdados de {ano} não extraídos em {destino}.\n"
            f"Rode: censo obter {ano}"
        )
    return destino


def localizar_csv_escolas(ano: int, *, paths: Paths | None = None) -> Path:
    """Encontra o CSV de escolas dentro do diretório extraído de ``ano``."""
    raiz = _dir_extraido(ano, paths or get_paths())
    candidatos = [
        arquivo
        for arquivo in raiz.rglob("*")
        if arquivo.is_file()
        and any(re.match(p, arquivo.name, re.IGNORECASE) for p in _PADROES_ESCOLAS)
    ]
    if not candidatos:
        raise FileNotFoundError(
            f"Nenhum CSV de escolas encontrado sob {raiz}. "
            f"Padrões testados: {_PADROES_ESCOLAS}"
        )
    # Se houver mais de um, o maior é o arquivo completo (os outros costumam
    # ser suplementos ou amostras).
    return max(candidatos, key=lambda p: p.stat().st_size)


def colunas_disponiveis(ano: int, *, paths: Paths | None = None) -> list[str]:
    """Lê apenas o cabeçalho do CSV e devolve a lista de colunas do ano."""
    csv = localizar_csv_escolas(ano, paths=paths)
    cabecalho = pd.read_csv(csv, sep=SEPARADOR, encoding=ENCODING, nrows=0)
    return list(cabecalho.columns)


#: Colunas que têm cara de código numérico pelo prefixo, mas são alfanuméricas
#: no arquivo do INEP. ``CO_ORGAO_REGIONAL``, por exemplo, traz valores como
#: ``0MI11`` em parte dos estados. A lista é um atalho: o
#: ``_ler_csv_tolerante`` descobre sozinho casos novos, e esta lista só evita a
#: releitura do CSV nos casos já conhecidos.
_CODIGOS_TEXTO = frozenset({"CO_ORGAO_REGIONAL"})


def _dtypes_para(colunas: list[str]) -> dict[str, str]:
    """Escolhe dtypes econômicos a partir dos prefixos padronizados do INEP."""
    dtypes: dict[str, str] = {}
    for coluna in colunas:
        if coluna in _CODIGOS_TEXTO:
            dtypes[coluna] = "string"
        elif coluna.startswith(("IN_", "TP_")):
            # Nullable: essas colunas usam vazio para "não aplicável".
            dtypes[coluna] = "Int8"
        elif coluna.startswith("QT_"):
            dtypes[coluna] = "Int32"
        elif coluna.startswith("CO_"):
            dtypes[coluna] = "Int64"
        elif coluna.startswith(("NO_", "SG_", "DS_")):
            dtypes[coluna] = "string"
    return dtypes


def carregar_escolas(
    ano: int,
    *,
    colunas: list[str] | None = None,
    uf: str | list[str] | None = None,
    apenas_ativas: bool = True,
    paths: Paths | None = None,
    usar_parquet: bool = True,
) -> pd.DataFrame:
    """Carrega o arquivo de escolas de ``ano`` como DataFrame.

    :param colunas: colunas a ler. Por padrão, ``COLUNAS_BASICAS`` +
        ``COLUNAS_QUANTITATIVAS``. Para ler tudo, passe
        ``colunas=colunas_disponiveis(ano)``.
    :param uf: filtra por sigla de UF (ex.: ``"MG"`` ou ``["MG", "SP"]``).
    :param apenas_ativas: mantém só escolas em atividade
        (``TP_SITUACAO_FUNCIONAMENTO == 1``), o padrão para quase toda análise
        descritiva. Requer que essa coluna esteja entre as lidas.
    :param usar_parquet: se houver um Parquet em ``data/processed/``, lê dele.

    Colunas pedidas que não existirem no ano são ignoradas silenciosamente — o
    INEP renomeia e aposenta variáveis entre edições, e travar a leitura por
    causa disso inviabilizaria comparações entre anos.
    """
    paths = paths or get_paths()
    pedidas = list(colunas) if colunas is not None else [*COLUNAS_BASICAS, *COLUNAS_QUANTITATIVAS]

    parquet = paths.processed / f"escolas_{ano}.parquet"
    df = None
    if usar_parquet and parquet.exists():
        no_parquet = _colunas_do_parquet(parquet)
        efetivas = [c for c in pedidas if c in no_parquet]
        faltando = [c for c in pedidas if c not in no_parquet]
        # Só voltamos ao CSV se o que falta no Parquet existir de fato lá.
        if efetivas and not (faltando and set(faltando) & _colunas_do_csv_ou_vazio(ano, paths)):
            df = pd.read_parquet(parquet, columns=efetivas)
    if df is None:
        df = _ler_csv(ano, pedidas, paths)

    if apenas_ativas and "TP_SITUACAO_FUNCIONAMENTO" in df.columns:
        df = df[df["TP_SITUACAO_FUNCIONAMENTO"] == 1]

    if uf is not None:
        if "SG_UF" not in df.columns:
            raise KeyError("filtro por UF exige a coluna SG_UF entre as colunas lidas")
        siglas = [uf] if isinstance(uf, str) else list(uf)
        df = df[df["SG_UF"].isin(siglas)]

    return df.reset_index(drop=True)


def _colunas_do_parquet(caminho: Path) -> set[str]:
    """Lê só o esquema do Parquet, sem carregar dados."""
    import pyarrow.parquet as pq

    return set(pq.ParquetFile(caminho).schema.names)


def _colunas_do_csv_ou_vazio(ano: int, paths: Paths) -> set[str]:
    """Colunas do CSV do ano, ou conjunto vazio se o CSV não estiver por perto.

    Quem apaga ``data/interim/`` depois de gerar o Parquet ainda deve conseguir
    trabalhar — por isso a ausência do CSV não é erro aqui.
    """
    try:
        return set(colunas_disponiveis(ano, paths=paths))
    except FileNotFoundError:
        return set()


def _ler_csv(ano: int, pedidas: list[str], paths: Paths) -> pd.DataFrame:
    csv = localizar_csv_escolas(ano, paths=paths)
    existentes = set(pd.read_csv(csv, sep=SEPARADOR, encoding=ENCODING, nrows=0).columns)
    efetivas = [c for c in pedidas if c in existentes]
    if not efetivas:
        raise KeyError(
            f"Nenhuma das colunas pedidas existe em {ano}. "
            f"Veja colunas_disponiveis({ano})."
        )
    try:
        return pd.read_csv(
            csv,
            sep=SEPARADOR,
            encoding=ENCODING,
            usecols=efetivas,
            dtype=_dtypes_para(efetivas),
        )[efetivas]
    except ValueError:
        # Alguma coluna não é numérica apesar do prefixo. Em vez de exigir que
        # a lista `_CODIGOS_TEXTO` esteja sempre em dia com o INEP, relemos em
        # modo tolerante e deixamos os dados decidirem o tipo.
        return _ler_csv_tolerante(csv, efetivas)


def _ler_csv_tolerante(csv: Path, efetivas: list[str]) -> pd.DataFrame:
    """Lê tudo como texto e converte coluna a coluna, sem perder valor algum.

    O que não converter para número continua como texto — é o comportamento
    correto para códigos alfanuméricos do INEP, que um ``errors="coerce"``
    transformaria em nulo silenciosamente.
    """
    df = pd.read_csv(
        csv,
        sep=SEPARADOR,
        encoding=ENCODING,
        usecols=efetivas,
        dtype="string",
    )[efetivas]

    textuais: list[str] = []
    for coluna, tipo in _dtypes_para(efetivas).items():
        if tipo == "string":
            continue
        try:
            df[coluna] = pd.to_numeric(df[coluna]).astype(tipo)
        except (ValueError, TypeError):
            textuais.append(coluna)

    if textuais:
        warnings.warn(
            "Colunas lidas como texto por conterem valores não numéricos: "
            + ", ".join(sorted(textuais)),
            stacklevel=2,
        )
    return df


def converter_para_parquet(
    ano: int,
    *,
    colunas: list[str] | None = None,
    paths: Paths | None = None,
    forcar: bool = False,
) -> Path:
    """Converte o CSV de escolas de ``ano`` para Parquet em ``data/processed/``.

    Por padrão grava *todas* as colunas do ano, para que o Parquet possa servir
    a qualquer análise posterior sem voltar ao CSV.
    """
    paths = (paths or get_paths()).criar()
    destino = paths.processed / f"escolas_{ano}.parquet"
    if destino.exists() and not forcar:
        return destino

    todas = colunas if colunas is not None else colunas_disponiveis(ano, paths=paths)
    df = _ler_csv(ano, todas, paths)
    df.to_parquet(destino, index=False)
    return destino


def carregar_anos(
    anos: list[int],
    *,
    colunas: list[str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Empilha vários anos num único DataFrame (para séries históricas)."""
    quadros = [carregar_escolas(ano, colunas=colunas, **kwargs) for ano in anos]
    return pd.concat(quadros, ignore_index=True)
