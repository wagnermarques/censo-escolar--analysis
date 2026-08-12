"""Testes da tipagem na leitura dos CSVs.

O INEP mistura códigos numéricos e alfanuméricos sob o mesmo prefixo ``CO_``,
e o dtype é escolhido por prefixo. Estes testes fixam o comportamento quando a
heurística erra: nada de estourar exceção, nada de virar nulo.
"""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

from censo_escolar.config import ENCODING, SEPARADOR
from censo_escolar.loading import _dtypes_para, _ler_csv, _ler_csv_tolerante


def _escrever_csv(caminho, linhas: list[str]) -> None:
    caminho.write_text("\n".join(linhas) + "\n", encoding=ENCODING)


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("microdados_ed_basica_2024.csv", True),
        ("Tabela_Escola_2025_V2.csv", True),  # nomenclatura nova de 2025
        ("Tabela_Escola_2026.csv", True),  # sem o sufixo de versão
        ("ESCOLAS.CSV", True),
        # O pacote de 2025 traz uma tabela por entidade. Nenhuma das outras
        # pode ser confundida com a de escolas — em especial a de gestores,
        # cujo nome contém "Escolar".
        ("Tabela_Gestor_Escolar_2025_v2.csv", False),
        ("Tabela_Matricula_2025_V2.csv", False),
        ("Tabela_Docente_2025_V2.csv", False),
        ("Tabela_Turma_2025_V2.csv", False),
        ("Tabela_Curso_Tecnico_2025_V2.csv", False),
        ("suplemento_cursos_tecnicos_2024.csv", False),
    ],
)
def test_padroes_do_csv_de_escolas(nome, esperado):
    import re

    from censo_escolar.loading import _PADROES_ESCOLAS

    casa = any(re.match(p, nome, re.IGNORECASE) for p in _PADROES_ESCOLAS)
    assert casa is esperado


def test_dtypes_por_prefixo():
    dtypes = _dtypes_para(
        ["IN_INTERNET", "TP_DEPENDENCIA", "QT_MAT_BAS", "CO_MUNICIPIO", "NO_ENTIDADE"]
    )
    assert dtypes["IN_INTERNET"] == "Int8"
    assert dtypes["TP_DEPENDENCIA"] == "Int8"
    assert dtypes["QT_MAT_BAS"] == "Int32"
    assert dtypes["CO_MUNICIPIO"] == "Int64"
    assert dtypes["NO_ENTIDADE"] == "string"


def test_codigo_alfanumerico_conhecido_vira_texto():
    # CO_ORGAO_REGIONAL tem prefixo de código numérico, mas traz valores
    # como "0MI11" em parte dos estados.
    assert _dtypes_para(["CO_ORGAO_REGIONAL"])["CO_ORGAO_REGIONAL"] == "string"


def test_leitura_tolerante_preserva_valor_alfanumerico(tmp_path):
    csv = tmp_path / "escolas.csv"
    _escrever_csv(
        csv,
        [
            f"CO_MUNICIPIO{SEPARADOR}CO_DESCONHECIDO{SEPARADOR}QT_MAT_BAS",
            f"3106200{SEPARADOR}0MI11{SEPARADOR}120",
            f"3550308{SEPARADOR}00009{SEPARADOR}340",
        ],
    )
    colunas = ["CO_MUNICIPIO", "CO_DESCONHECIDO", "QT_MAT_BAS"]

    with pytest.warns(UserWarning, match="CO_DESCONHECIDO"):
        df = _ler_csv_tolerante(csv, colunas)

    # A coluna problemática continua texto, com o valor intacto...
    assert df["CO_DESCONHECIDO"].tolist() == ["0MI11", "00009"]
    # ...e as demais mantêm os dtypes econômicos.
    assert str(df["CO_MUNICIPIO"].dtype) == "Int64"
    assert str(df["QT_MAT_BAS"].dtype) == "Int32"


def test_ler_csv_cai_no_modo_tolerante_sozinho(tmp_path, monkeypatch):
    """Uma coluna alfanumérica desconhecida não pode quebrar a leitura."""
    csv = tmp_path / "microdados_ed_basica_2023.csv"
    _escrever_csv(
        csv,
        [
            f"CO_MUNICIPIO{SEPARADOR}CO_NOVO_CODIGO",
            f"3106200{SEPARADOR}0MI11",
            f"3550308{SEPARADOR}0MI12",
        ],
    )
    monkeypatch.setattr("censo_escolar.loading.localizar_csv_escolas", lambda ano, paths=None: csv)

    with pytest.warns(UserWarning):
        df = _ler_csv(2023, ["CO_MUNICIPIO", "CO_NOVO_CODIGO"], paths=None)

    assert df["CO_NOVO_CODIGO"].tolist() == ["0MI11", "0MI12"]
    assert len(df) == 2


def test_leitura_normal_nao_emite_aviso(tmp_path):
    """Sem valor estranho, o caminho tolerante não deve reclamar de nada."""
    csv = tmp_path / "escolas.csv"
    _escrever_csv(
        csv,
        [
            f"CO_MUNICIPIO{SEPARADOR}QT_MAT_BAS",
            f"3106200{SEPARADOR}120",
        ],
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        df = _ler_csv_tolerante(csv, ["CO_MUNICIPIO", "QT_MAT_BAS"])
    assert str(df["CO_MUNICIPIO"].dtype) == "Int64"


def test_valores_vazios_continuam_nulos(tmp_path):
    """Campo vazio do INEP é 'não aplicável', não zero."""
    csv = tmp_path / "escolas.csv"
    _escrever_csv(
        csv,
        [
            f"CO_MUNICIPIO{SEPARADOR}CO_ALFA{SEPARADOR}IN_INTERNET",
            f"3106200{SEPARADOR}0MI11{SEPARADOR}",
            f"3550308{SEPARADOR}00009{SEPARADOR}1",
        ],
    )
    with pytest.warns(UserWarning):
        df = _ler_csv_tolerante(csv, ["CO_MUNICIPIO", "CO_ALFA", "IN_INTERNET"])
    assert pd.isna(df["IN_INTERNET"].iloc[0])
    assert df["IN_INTERNET"].iloc[1] == 1
