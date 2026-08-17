"""Testes da detecção de esquema e do dicionário de dados.

O que estes testes fixam é o que a série histórica depende: quais colunas são
comuns a todos os anos, e qual tipo comporta cada uma em *todos* eles. Os dois
erros que interessam são silenciosos — uma coluna que sumiu num ano vira ``NaN``
somável, e um tipo que muda entre anos vira ``object`` na concatenação —, então
cada caso abaixo constrói o cenário de propósito.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from censo_escolar import esquema
from censo_escolar.config import ENCODING, SEPARADOR, Paths, get_paths


def _paths(tmp_path: Path) -> Paths:
    """Um :class:`Paths` inteiro dentro de ``tmp_path``, sem tocar no projeto."""
    padrao = get_paths()
    campos = {campo: tmp_path / valor.name for campo, valor in vars(padrao).items()}
    campos["raiz"] = tmp_path
    campos["data"] = tmp_path / "data"
    for chave in ("raw", "interim", "processed"):
        campos[chave] = campos["data"] / chave
    return Paths(**campos)


def _criar_ano(paths: Paths, ano: int, linhas: list[str]) -> Path:
    """Escreve um CSV de escolas mínimo no lugar onde a extração o deixaria."""
    destino = paths.interim / f"microdados_censo_escolar_{ano}" / "dados"
    destino.mkdir(parents=True, exist_ok=True)
    csv = destino / f"microdados_ed_basica_{ano}.csv"
    csv.write_text("\n".join(linhas) + "\n", encoding=ENCODING)
    return csv


def _linha(*valores: str) -> str:
    return SEPARADOR.join(valores)


@pytest.fixture
def anos_falsos(tmp_path) -> Paths:
    """Três anos com colunas que entram, saem e mudam de tipo no meio do caminho."""
    paths = _paths(tmp_path)
    # 2021: tem QT_MAT_BAS; CO_ORGAO_REGIONAL ainda é numérico puro.
    _criar_ano(
        paths,
        2021,
        [
            _linha("NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "CO_ORGAO_REGIONAL",
                   "QT_MAT_BAS", "IN_BIBLIOTECA"),
            _linha("2021", "11000023", "3", "11", "1200", "1"),
            _linha("2021", "11000040", "4", "12", "80", "0"),
        ],
    )
    # 2022: mesma cara, valores maiores (o dtype tem de comportar os dois anos).
    _criar_ano(
        paths,
        2022,
        [
            _linha("NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "CO_ORGAO_REGIONAL",
                   "QT_MAT_BAS", "IN_BIBLIOTECA"),
            _linha("2022", "11000023", "3", "13", "40000", "1"),
            _linha("2022", "11000040", "2", "14", "500", ""),
        ],
    )
    # 2023: QT_MAT_BAS foi embora, NO_ENTIDADE chegou, e CO_ORGAO_REGIONAL
    # passou a trazer código alfanumérico — as três mudanças que quebram série.
    _criar_ano(
        paths,
        2023,
        [
            _linha("NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "CO_ORGAO_REGIONAL",
                   "IN_BIBLIOTECA", "NO_ENTIDADE"),
            _linha("2023", "11000023", "3", "0MI11", "1", "ESCOLA A"),
            _linha("2023", "11000040", "2", "0MI12", "0", "ESCOLA B"),
        ],
    )
    return paths


# --------------------------------------------------------------------------
# Presença
# --------------------------------------------------------------------------


def test_anos_disponiveis_ignora_diretorio_sem_csv(anos_falsos, tmp_path):
    (anos_falsos.interim / "microdados_censo_escolar_2030").mkdir(parents=True)
    assert esquema.anos_disponiveis(paths=anos_falsos) == [2021, 2022, 2023]


def test_matriz_presenca_marca_entrada_e_saida(anos_falsos):
    matriz = esquema.matriz_presenca([2021, 2022, 2023], paths=anos_falsos)
    assert matriz.loc["QT_MAT_BAS"].tolist() == [True, True, False]
    assert matriz.loc["NO_ENTIDADE"].tolist() == [False, False, True]
    assert matriz.loc["CO_ENTIDADE"].all()


def test_contagem_por_ano_conta_o_arquivo_de_cada_edicao(anos_falsos):
    matriz = esquema.matriz_presenca([2021, 2022, 2023], paths=anos_falsos)
    contagem = esquema.contagem_por_ano(matriz)
    assert list(contagem["ano"]) == [2021, 2022, 2023]
    assert list(contagem["variaveis"]) == [6, 6, 6]


def test_colunas_comuns_exclui_quem_falta_em_um_ano(anos_falsos):
    comuns = esquema.colunas_comuns([2021, 2022, 2023], paths=anos_falsos)
    assert "QT_MAT_BAS" not in comuns
    assert "NO_ENTIDADE" not in comuns
    assert {"NU_ANO_CENSO", "CO_ENTIDADE", "TP_DEPENDENCIA", "IN_BIBLIOTECA"} <= set(comuns)
    # Sem 2023 no recorte, QT_MAT_BAS volta a ser comparável.
    assert "QT_MAT_BAS" in esquema.colunas_comuns([2021, 2022], paths=anos_falsos)


def test_resumo_presenca_separa_buraco_no_meio_de_serie_curta(tmp_path):
    """Uma variável que some num ano do meio é o caso que engana."""
    paths = _paths(tmp_path)
    for ano, colunas in ((2021, ("CO_ENTIDADE", "IN_X")), (2022, ("CO_ENTIDADE",)),
                         (2023, ("CO_ENTIDADE", "IN_X"))):
        _criar_ano(paths, ano, [_linha(*colunas), _linha(*["1"] * len(colunas))])

    resumo = esquema.resumo_presenca([2021, 2022, 2023], paths=paths).set_index("coluna")
    assert resumo.loc["IN_X", "n_anos"] == 2
    assert resumo.loc["IN_X", "comum"] is False or not resumo.loc["IN_X", "comum"]
    assert not resumo.loc["IN_X", "continua"]
    assert resumo.loc["IN_X", "anos_ausentes"] == "2022"
    assert resumo.loc["CO_ENTIDADE", "continua"]


# --------------------------------------------------------------------------
# Tipos, a partir dos dados
# --------------------------------------------------------------------------


def test_perfilar_escolhe_o_inteiro_mais_estreito(anos_falsos):
    perfil = esquema.perfilar(2021, paths=anos_falsos).set_index("coluna")
    assert perfil.loc["TP_DEPENDENCIA", "dtype_dados"] == "Int8"
    assert perfil.loc["IN_BIBLIOTECA", "dtype_dados"] == "Int8"
    assert perfil.loc["QT_MAT_BAS", "dtype_dados"] == "Int16"
    # CO_ENTIDADE tem 8 dígitos: não cabe em Int16.
    assert perfil.loc["CO_ENTIDADE", "dtype_dados"] == "Int32"


def test_perfilar_detecta_codigo_alfanumerico_pelos_dados(anos_falsos):
    perfil = esquema.perfilar(2023, paths=anos_falsos).set_index("coluna")
    assert perfil.loc["CO_ORGAO_REGIONAL", "dtype_dados"] == "string"


def test_zero_a_esquerda_impede_virar_inteiro(tmp_path):
    """``00009`` é identificador; um Int64 comeria o zero sem avisar."""
    paths = _paths(tmp_path)
    _criar_ano(
        paths,
        2023,
        [_linha("CO_MUNICIPIO", "CO_CODIGO"), _linha("3106200", "00009"),
         _linha("3550308", "00010")],
    )
    perfil = esquema.perfilar(2023, paths=paths).set_index("coluna")
    assert perfil.loc["CO_CODIGO", "dtype_dados"] == "string"
    assert bool(perfil.loc["CO_CODIGO", "zeros_a_esquerda"])
    assert perfil.loc["CO_MUNICIPIO", "dtype_dados"] == "Int32"


def test_conflito_marca_só_a_perda_de_informacao(tmp_path):
    """Prefixo largo demais não é conflito; prefixo estreito demais é."""
    paths = _paths(tmp_path)
    _criar_ano(
        paths,
        2023,
        [_linha("CO_UF", "CO_NOVO"), _linha("31", "0MI11"), _linha("35", "0MI12")],
    )
    perfil = esquema.perfilar(2023, paths=paths).set_index("coluna")
    # CO_UF: prefixo diz Int64, os dados cabem em Int8. Desperdício, não perda.
    assert perfil.loc["CO_UF", "dtype_prefixo"] == "Int64"
    assert perfil.loc["CO_UF", "dtype_dados"] == "Int8"
    assert not perfil.loc["CO_UF", "conflito"]
    # CO_NOVO: o prefixo levaria a leitura a estourar. Isso é conflito.
    assert perfil.loc["CO_NOVO", "dtype_dados"] == "string"
    assert perfil.loc["CO_NOVO", "conflito"]


def test_coluna_toda_vazia_nao_inventa_tipo(tmp_path):
    paths = _paths(tmp_path)
    _criar_ano(
        paths,
        2023,
        [_linha("CO_ENTIDADE", "QT_NADA"), _linha("11000023", ""), _linha("11000040", "")],
    )
    perfil = esquema.perfilar(2023, paths=paths).set_index("coluna")
    assert perfil.loc["QT_NADA", "dtype_dados"] == esquema.VAZIO
    assert perfil.loc["QT_NADA", "pct_nulo"] == 1.0


def test_perfilar_independe_do_tamanho_do_bloco(anos_falsos):
    """O bloco controla memória, não resultado — inclusive no min/max."""
    inteiro = esquema.perfilar(2022, paths=anos_falsos, tamanho_bloco=100)
    picado = esquema.perfilar(2022, paths=anos_falsos, tamanho_bloco=1)
    pd.testing.assert_frame_equal(inteiro, picado)


@pytest.mark.parametrize(
    ("tipos", "esperado"),
    [
        (["Int8", "Int8"], "Int8"),
        (["Int8", "Int32"], "Int32"),
        (["Int32", "Float64"], "Float64"),
        # O caso que motiva a promoção: um ano numérico, outro alfanumérico.
        (["Int64", "string"], "string"),
        # Ano vazio não é evidência de tipo nenhum e não rebaixa a decisão.
        ([esquema.VAZIO, "Int8"], "Int8"),
        ([esquema.VAZIO, esquema.VAZIO], esquema.VAZIO),
    ],
)
def test_promover_pega_o_tipo_que_serve_a_todos(tipos, esperado):
    assert esquema.promover(tipos) == esperado


# --------------------------------------------------------------------------
# O dicionário
# --------------------------------------------------------------------------


def test_dicionario_marca_tipo_instavel_entre_anos(anos_falsos):
    dic = esquema.dicionario_de_dados(
        [2021, 2022, 2023], incluir_descricao=False, paths=anos_falsos
    ).set_index("coluna")

    # Só as comuns entram por padrão.
    assert "QT_MAT_BAS" not in dic.index
    # CO_ORGAO_REGIONAL é Int8 em 2021/2022 e string em 2023: instável, e o
    # tipo que serve à série é o mais largo.
    assert not dic.loc["CO_ORGAO_REGIONAL", "tipo_estavel"]
    assert dic.loc["CO_ORGAO_REGIONAL", "dtype_serie"] == "string"
    assert "2023:string" in dic.loc["CO_ORGAO_REGIONAL", "tipos_por_ano"]
    # As estáveis não carregam o detalhe por ano, que só polui.
    assert dic.loc["TP_DEPENDENCIA", "tipo_estavel"]
    assert dic.loc["TP_DEPENDENCIA", "tipos_por_ano"] == ""


def test_dicionario_com_todas_as_colunas_marca_quem_nao_e_comum(anos_falsos):
    dic = esquema.dicionario_de_dados(
        [2021, 2022, 2023], apenas_comuns=False, incluir_descricao=False, paths=anos_falsos
    ).set_index("coluna")
    assert not dic.loc["QT_MAT_BAS", "comum"]
    assert dic.loc["QT_MAT_BAS", "anos_ausentes"] == "2023"
    assert dic.loc["CO_ENTIDADE", "comum"]


def test_dtypes_para_serie_historica_alimenta_o_pandas(anos_falsos):
    dic = esquema.dicionario_de_dados(
        [2021, 2022], incluir_descricao=False, paths=anos_falsos
    )
    dtypes = esquema.dtypes_para_serie_historica(dic)
    # QT_MAT_BAS vai a 40000 em 2022: Int16 não serve aos dois anos.
    assert dtypes["QT_MAT_BAS"] == "Int32"
    assert dtypes["TP_DEPENDENCIA"] == "Int8"

    csv = anos_falsos.interim / "microdados_censo_escolar_2022" / "dados"
    df = pd.read_csv(
        csv / "microdados_ed_basica_2022.csv",
        sep=SEPARADOR,
        encoding=ENCODING,
        dtype=dtypes,
    )
    assert str(df["QT_MAT_BAS"].dtype) == "Int32"


def test_salvar_e_carregar_preservam_o_dicionario(anos_falsos):
    dic = esquema.dicionario_de_dados(
        [2021, 2022], incluir_descricao=False, paths=anos_falsos
    )
    destino = esquema.salvar_dicionario(dic, paths=anos_falsos)
    assert destino.exists()
    lido = esquema.carregar_dicionario(paths=anos_falsos)
    assert list(lido["coluna"]) == list(dic["coluna"])
    assert list(lido["dtype_serie"]) == list(dic["dtype_serie"])


def test_carregar_dicionario_ausente_diz_o_que_fazer(tmp_path):
    with pytest.raises(FileNotFoundError, match="censo dicionario"):
        esquema.carregar_dicionario(paths=_paths(tmp_path))


# --------------------------------------------------------------------------
# A planilha do INEP
# --------------------------------------------------------------------------


def _escrever_planilha(caminho: Path, linhas: list[list[object]], aba: str) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    for linha in linhas:
        ws.append(linha)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)


def test_ler_dicionario_inep_acha_o_cabecalho_deslocado(tmp_path):
    """Título, legenda e cabeçalho de duas alturas antes dos dados — como vem."""
    paths = _paths(tmp_path)
    anexos = paths.interim / "microdados_censo_escolar_2023" / "Anexos" / "ANEXO I"
    _escrever_planilha(
        anexos / "dicionário_dados_educação_básica.xlsx",
        [
            ["Dicionário de Variáveis - Tabela de Escolas"],
            [],
            ["N", "Nome da Variável", "Descrição da Variável", "Tipo", "Tam.(1)", "Categoria"],
            [None, None, None, None, None, None],
            ["1", "TP_DEPENDENCIA", "Dependência Administrativa", "Num", "1",
             "1 - Federal\n2 - Estadual"],
            ["2", "CO_ORGAO_REGIONAL", "Código do Órgão Regional", "Char", "5", None],
            [None, "Nota: (1) tamanho em caracteres.", None, None, None, None],
        ],
        aba="microdados_unidade_coleta",
    )

    dic = esquema.ler_dicionario_inep(2023, paths=paths).set_index("coluna")
    assert dic.loc["TP_DEPENDENCIA", "descricao"] == "Dependência Administrativa"
    # As categorias vêm em várias linhas dentro de uma célula só.
    assert dic.loc["TP_DEPENDENCIA", "categorias"] == "1 - Federal | 2 - Estadual"
    # O INEP declara este como texto — a mesma conclusão a que os dados chegam.
    assert dic.loc["CO_ORGAO_REGIONAL", "tipo_inep"] == "Char"
    # A linha de nota de rodapé não é variável.
    assert len(dic) == 2


def test_aba_de_escolas_nao_confunde_com_a_de_gestores():
    # "Gestor Escolar" contém "Escolar"; a de escolas é outra.
    assert (
        esquema._aba_de_escolas(
            ["Tabela_de_Gestor", "Tabela_de_Escola", "Tabela_de_Matrícula"]
        )
        == "Tabela_de_Escola"
    )
    assert esquema._aba_de_escolas(["Cadastro_Escolas"]) == "Cadastro_Escolas"
    assert esquema._aba_de_escolas(["microdados_unidade_coleta"]) == "microdados_unidade_coleta"


def test_planilha_de_bloqueio_do_excel_e_ignorada(tmp_path):
    """Alguns ZIPs trazem o ``~$...xlsx`` que o Excel deixa para trás."""
    paths = _paths(tmp_path)
    anexos = paths.interim / "microdados_censo_escolar_2022" / "Anexos"
    anexos.mkdir(parents=True)
    lixo = anexos / "~$dicionário_dados.xlsx"
    lixo.write_bytes(b"nao e uma planilha" * 100)
    _escrever_planilha(
        anexos / "dicionário_dados.xlsx",
        [["N", "Nome da Variável", "Descrição da Variável", "Tipo", "Tam.(1)", "Categoria"],
         ["1", "CO_ENTIDADE", "Código da Escola", "Num", "8", None]],
        aba="Cadastro_Escolas",
    )
    # O de bloqueio é maior, e o desempate por tamanho pegaria ele.
    assert lixo.stat().st_size > 0
    assert esquema.localizar_dicionario_inep(2022, paths=paths).name.startswith("dicion")
