"""Testes do arquivo que define o site (``consultas.txt``) e das páginas.

A ideia que estes testes protegem: o site é *função* de ``consultas.txt``. Se
uma consulta não sobreviver à ida e volta ao arquivo, `make site` reconstrói
um site diferente do que se pediu — e o erro só apareceria na página.
"""

from __future__ import annotations

import json

import pytest

from censo_escolar import sitio
from censo_escolar.config import get_paths

URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados/35"
    "?intrarregiao=microrregiao&qualidade=minima&formato=application/vnd.geo+json"
)


@pytest.fixture()
def paths(tmp_path):
    """Um projeto de mentira, para não escrever no site de verdade."""
    return get_paths(tmp_path)


def test_ida_e_volta_preserva_a_consulta():
    consulta = sitio.Consulta("QT_MAT_BAS", URL, [2019, 2023], {})
    assert sitio.analisar_linha(consulta.linha()) == consulta


def test_titulo_com_espaco_sobrevive_a_ida_e_volta():
    """O caso que quebrou de verdade: TITULO="Escolas privadas" sem aspas."""
    consulta = sitio.Consulta("TP_DEPENDENCIA", URL, [2023], {"TITULO": "Escolas privadas por UF"})
    de_volta = sitio.analisar_linha(consulta.linha())
    assert de_volta.opcoes["TITULO"] == "Escolas privadas por UF"


def test_linha_reconhece_cada_palavra_pelo_que_ela_e():
    consulta = sitio.analisar_linha(f'qt_mat_bas "{URL}" 2023 2024 CATEGORIA=4')
    assert consulta.variavel == "QT_MAT_BAS"  # normaliza a caixa
    assert consulta.url == URL
    assert consulta.anos == [2023, 2024]
    assert consulta.opcoes == {"CATEGORIA": "4"}


@pytest.mark.parametrize("linha", ["", "   ", "# comentário", "  # indentado"])
def test_linhas_vazias_e_comentarios_sao_ignoradas(linha):
    assert sitio.analisar_linha(linha) is None


def test_linha_sem_url_e_erro():
    with pytest.raises(ValueError, match="sem variável ou sem URL"):
        sitio.analisar_linha("QT_MAT_BAS 2023")


def test_registrar_a_mesma_consulta_atualiza_em_vez_de_duplicar(paths):
    sitio.registrar_consulta(sitio.Consulta("QT_MAT_BAS", URL, [2023], {}), paths=paths)
    sitio.registrar_consulta(sitio.Consulta("QT_MAT_BAS", URL, [2019, 2024], {}), paths=paths)

    consultas = sitio.ler_consultas(paths=paths)
    assert len(consultas) == 1
    assert consultas[0].anos == [2019, 2024]


def test_consultas_diferentes_convivem(paths):
    sitio.registrar_consulta(sitio.Consulta("QT_MAT_BAS", URL, [2023], {}), paths=paths)
    sitio.registrar_consulta(sitio.Consulta("IN_INTERNET", URL, [2023], {}), paths=paths)
    assert [c.variavel for c in sitio.ler_consultas(paths=paths)] == ["QT_MAT_BAS", "IN_INTERNET"]


def test_erro_de_leitura_diz_o_arquivo_e_a_linha(paths):
    arquivo = sitio.caminho_consultas(paths)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text("# ok\nQT_MAT_BAS 2023\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"consultas\.txt:2"):
        sitio.ler_consultas(paths=paths)


def test_indice_substitui_pelo_slug(paths):
    sitio.atualizar_indice({"slug": "a", "titulo": "A"}, paths=paths)
    sitio.atualizar_indice({"slug": "b", "titulo": "B"}, paths=paths)
    sitio.atualizar_indice({"slug": "a", "titulo": "A2"}, paths=paths)

    indice = sitio.ler_indice(paths=paths)
    assert [m["slug"] for m in indice] == ["b", "a"]
    assert indice[-1]["titulo"] == "A2"


def test_pagina_sai_com_o_essencial(paths):
    destino = sitio.escrever_pagina(
        "qt-mat-bas-uf-br-2023",
        titulo="Matrículas por UF",
        subtitulo="Soma por área",
        descricao="Número de Matrículas da Educação Básica",
        rodape="<p>fonte</p>",
        anos=[2019, 2023],
        unidade="",
        paths=paths,
    )
    html = destino.read_text(encoding="utf-8")
    assert "<title>Matrículas por UF</title>" in html
    assert '../dados/" + SLUG + ".geojson' in html
    assert "[2019, 2023]" in html  # o seletor de ano
    assert "{{" not in html  # nenhum marcador ficou por preencher


def test_pagina_escapa_html_do_titulo(paths):
    destino = sitio.escrever_pagina(
        "x",
        titulo="Escolas <script>alert(1)</script>",
        subtitulo="",
        descricao="",
        rodape="",
        anos=[2023],
        unidade="",
        paths=paths,
    )
    assert "<script>alert(1)</script>" not in destino.read_text(encoding="utf-8")


def test_index_lista_os_mapas(paths):
    destino = sitio.gerar_index(
        [
            {
                "slug": "qt-mat-bas-uf-br-2023",
                "titulo": "Matrículas por UF",
                "descricao": "d",
                "variavel": "QT_MAT_BAS",
                "anos": [2023],
                "grao": "uf",
                "areas": 27,
            }
        ],
        paths=paths,
    )
    html = destino.read_text(encoding="utf-8")
    assert 'href="mapas/qt-mat-bas-uf-br-2023.html"' in html
    assert "Matrículas por UF" in html
    assert "27 áreas" in html


def test_index_vazio_nao_quebra(paths):
    assert "Nenhum mapa ainda" in sitio.gerar_index([], paths=paths).read_text(encoding="utf-8")


def test_vendor_e_copiado_para_o_site(paths):
    destino = sitio.garantir_vendor(paths=paths)
    for nome in sitio.VENDOR:
        assert (destino / nome).stat().st_size > 0


def test_entrada_de_indice_e_serializavel():
    """O índice vira JSON: um Path no meio quebraria a escrita."""
    resultado = {
        "slug": "s", "titulo": "t", "descricao": "d", "variavel": "QT_MAT_BAS",
        "anos": [2023], "grao": "uf", "areas": 27, "pagina": object(),
    }
    assert json.dumps(sitio.entrada_de_indice(resultado))
