"""Testes da leitura da URL do IBGE e da agregação que vira mapa.

O que precisa ficar fixado aqui é o contrato entre as duas fontes: o que a URL
do IBGE promete (recorte e grão) e o que os microdados entregam (a coluna
correspondente). Se esse contrato quebrar em silêncio, o mapa sai bonito e
errado — que é o pior desfecho possível.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from censo_escolar import mapas
from censo_escolar.mapas import ConsultaInvalida

BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"


def url(caminho: str, **params) -> str:
    consulta = "&".join(f"{c}={v}" for c, v in params.items())
    return f"{BASE}/{caminho}?{consulta}"


# --------------------------------------------------------------------------
# R1 e R2 — a URL é a consulta espacial
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intrarregiao", "coluna"),
    [
        ("UF", "CO_UF"),
        ("mesorregiao", "CO_MESORREGIAO"),
        ("microrregiao", "CO_MICRORREGIAO"),
        ("regiao-imediata", "CO_REGIAO_GEOG_IMED"),
        ("regiao-intermediaria", "CO_REGIAO_GEOG_INTERM"),
        ("municipio", "CO_MUNICIPIO"),
    ],
)
def test_intrarregiao_escolhe_a_coluna_de_agrupamento(intrarregiao, coluna):
    recorte = mapas.analisar_url(url("paises/BR", intrarregiao=intrarregiao, qualidade="minima"))
    assert recorte.coluna == coluna


def test_mesorregiao_e_intermediaria_nao_se_confundem():
    """Ambas usam código de 4 dígitos e são divisões diferentes.

    É por isso que o grão vem do ``intrarregiao`` da URL, e não de uma
    heurística sobre o formato do código.
    """
    meso = mapas.analisar_url(url("paises/BR", intrarregiao="mesorregiao", qualidade="minima"))
    inter = mapas.analisar_url(
        url("paises/BR", intrarregiao="regiao-intermediaria", qualidade="minima")
    )
    assert meso.coluna != inter.coluna


def test_caminho_vira_filtro_de_linhas():
    recorte = mapas.analisar_url(url("estados/35", intrarregiao="municipio", qualidade="minima"))
    assert (recorte.coluna_filtro, recorte.valor_filtro) == ("CO_UF", 35)


def test_uf_por_sigla_ou_por_codigo_dao_no_mesmo():
    por_sigla = mapas.analisar_url(url("estados/SP", intrarregiao="municipio", qualidade="minima"))
    por_codigo = mapas.analisar_url(url("estados/35", intrarregiao="municipio", qualidade="minima"))
    assert por_sigla.valor_filtro == por_codigo.valor_filtro == 35


def test_pais_sem_intrarregiao_e_recusado():
    """A malha do país sem grão é um polígono só — o mapa não diria nada."""
    with pytest.raises(ConsultaInvalida, match="intrarregiao"):
        mapas.analisar_url(url("paises/BR", qualidade="minima"))


def test_url_sem_aspas_vira_mensagem_util():
    """O shell corta a URL no primeiro `&`; o sintoma tem de virar instrução."""
    with pytest.raises(ConsultaInvalida, match="aspas"):
        mapas.analisar_url(f"{BASE}/estados/35?formato=application/vnd.geo+json")


def test_intrarregiao_desconhecido_lista_os_conhecidos():
    with pytest.raises(ConsultaInvalida, match="microrregiao"):
        mapas.analisar_url(url("paises/BR", intrarregiao="bairro", qualidade="minima"))


def test_url_de_outro_servidor_e_recusada():
    with pytest.raises(ConsultaInvalida, match="malha do IBGE"):
        mapas.analisar_url("https://exemplo.com/malhas/paises/BR?intrarregiao=UF")


def test_normalizar_acrescenta_o_formato_e_mantem_a_url_legivel():
    normalizada = mapas.normalizar_url(url("paises/BR", intrarregiao="UF"))
    assert "formato=application/vnd.geo+json" in normalizada
    assert "%2F" not in normalizada  # consultas.txt é para ler e editar à mão


def test_cache_endereca_pela_url(tmp_path, monkeypatch):
    from censo_escolar.config import get_paths

    paths = get_paths()
    a = mapas.caminho_malha(url("paises/BR", intrarregiao="UF", qualidade="minima"), paths=paths)
    b = mapas.caminho_malha(url("paises/BR", intrarregiao="UF", qualidade="maxima"), paths=paths)
    igual = mapas.caminho_malha(
        url("paises/BR", intrarregiao="UF", qualidade="minima"), paths=paths
    )
    assert a == igual and a != b


# --------------------------------------------------------------------------
# R4 — a natureza da variável decide o mapa
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("variavel", "modo"),
    [("QT_MAT_BAS", "soma"), ("IN_INTERNET", "taxa"), ("TP_DEPENDENCIA", "categoria")],
)
def test_agregacao_vem_da_natureza(variavel, modo):
    assert mapas.agregacao_de(variavel) == modo


@pytest.mark.parametrize("variavel", ["NO_ENTIDADE", "CO_MUNICIPIO", "DT_ANO_LETIVO_INICIO"])
def test_variavel_nao_mapeavel_e_recusada_com_alternativas(variavel):
    with pytest.raises(ConsultaInvalida, match="QT_"):
        mapas.agregacao_de(variavel)


# --------------------------------------------------------------------------
# R3 e R7 — junção por codarea e o GeoJSON com o dado dentro
# --------------------------------------------------------------------------


def _malha(*codigos: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": c},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            }
            for c in codigos
        ],
    }


def _dados(linhas) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=["ano", "codarea", "nome", "valor", "escolas"])


def test_uniao_casa_por_codarea_sem_conversao():
    geo, cobertura = mapas.unir(
        _malha("35", "31"),
        _dados([(2023, "35", "São Paulo", 10.0, 3), (2023, "31", "Minas", 4.0, 2)]),
        {"variavel": "QT_MAT_BAS"},
    )
    valores = {
        f["properties"]["codarea"]: f["properties"]["valores"]["2023"] for f in geo["features"]
    }
    assert valores == {"35": 10.0, "31": 4.0}
    assert cobertura["areas_com_dado"] == 2
    assert geo["meta"]["variavel"] == "QT_MAT_BAS"


def test_area_sem_dado_nao_some_do_mapa_e_entra_na_cobertura():
    """O polígono continua desenhado, vazio — e a falta é contada, não escondida."""
    geo, cobertura = mapas.unir(
        _malha("35", "31"), _dados([(2023, "35", "São Paulo", 10.0, 3)]), {}
    )
    assert cobertura == {
        "areas_na_malha": 2,
        "areas_com_dado": 1,
        "codigos_sem_poligono": [],
        "n_codigos_sem_poligono": 0,
    }
    sem_dado = [f for f in geo["features"] if f["properties"]["codarea"] == "31"][0]
    assert sem_dado["properties"]["valores"] == {}


def test_codigo_do_censo_sem_poligono_e_relatado():
    """Município criado ou extinto entre edições cai aqui."""
    _, cobertura = mapas.unir(
        _malha("35"),
        _dados([(2023, "35", "SP", 1.0, 1), (2023, "99", "Fantasma", 2.0, 1)]),
        {},
    )
    assert cobertura["n_codigos_sem_poligono"] == 1
    assert cobertura["codigos_sem_poligono"] == ["99"]


def test_varios_anos_viram_serie_na_mesma_area():
    geo, _ = mapas.unir(
        _malha("35"),
        _dados([(2019, "35", "SP", 8.0, 3), (2024, "35", "SP", 11.0, 4)]),
        {},
    )
    props = geo["features"][0]["properties"]
    assert props["valores"] == {"2019": 8.0, "2024": 11.0}
    assert props["escolas"] == {"2019": 3, "2024": 4}


# --------------------------------------------------------------------------
# R6 — nome determinístico
# --------------------------------------------------------------------------


def test_slug_e_estavel_e_sem_acento():
    recorte = mapas.analisar_url(url("estados/35", intrarregiao="microrregiao", qualidade="minima"))
    assert mapas.slug("QT_MAT_BAS", recorte, [2023]) == "qt-mat-bas-microrregiao-35-2023"
    assert mapas.slug("QT_MAT_BAS", recorte, [2019, 2024]) == "qt-mat-bas-microrregiao-35-2019-2024"


def test_slug_nao_muda_entre_execucoes():
    recorte = mapas.analisar_url(url("paises/BR", intrarregiao="UF", qualidade="minima"))
    assert mapas.slug("IN_INTERNET", recorte, [2023]) == mapas.slug("IN_INTERNET", recorte, [2023])


def test_geojson_gerado_e_json_valido():
    geo, _ = mapas.unir(_malha("35"), _dados([(2023, "35", "São Paulo", 1.0, 1)]), {"a": 1})
    assert json.loads(json.dumps(geo, ensure_ascii=False))["type"] == "FeatureCollection"
