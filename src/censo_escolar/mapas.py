"""Geração dos mapas estáticos a partir de uma variável do INEP e uma URL do IBGE.

O comando é ``censo map <VARIAVEL> <URL da malha> [anos]``, e a ideia toda
está em não inventar vocabulário: a URL de malha do IBGE *já* é uma linguagem
de recorte geográfico, oficial e documentada. Ela carrega as duas informações
que a agregação precisa —

- o caminho (``/estados/35``) diz **quais linhas** entram;
- o ``intrarregiao=`` diz **por qual coluna** agrupar;

— e o ``properties.codarea`` de cada polígono casa com o valor dessa coluna
sem conversão nenhuma, porque os dois vêm do mesmo IBGE.

O resultado é um GeoJSON com o dado já dentro (um arquivo, uma requisição) e
uma página HTML que só o desenha. As regras completas estão em
``georef-plan.org``, seções R1 a R9.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd

from censo_escolar import esquema, loading
from censo_escolar.codigos import MAPAS as MAPAS_DE_CODIGOS
from censo_escolar.codigos import UFS
from censo_escolar.config import Paths, get_paths

#: R2 — o ``intrarregiao=`` da URL diz por qual coluna agrupar, e em que anos
#: essa coluna existe. Os formatos de ``codarea`` foram conferidos na API:
#: ``11`` (UF), ``1102`` (meso *e* intermediária — veja o aviso abaixo),
#: ``110005`` (imediata), ``35035`` (micro), ``1100015`` (município).
#:
#: Atenção: mesorregião e região intermediária usam ambas códigos de 4
#: dígitos, e são divisões *diferentes*. Não dá para inferir o grão pelo
#: formato do código — é o ``intrarregiao`` que manda. É por isso que este
#: mapa existe em vez de uma heurística.
NIVEIS: dict[str, str] = {
    "uf": "CO_UF",
    "regiao-intermediaria": "CO_REGIAO_GEOG_INTERM",
    "mesorregiao": "CO_MESORREGIAO",
    "regiao-imediata": "CO_REGIAO_GEOG_IMED",
    "microrregiao": "CO_MICRORREGIAO",
    "municipio": "CO_MUNICIPIO",
}

#: O nome da área vem dos microdados, não da malha: as feições do IBGE trazem
#: só ``codarea``. Sem isto o popup mostraria um número e mais nada.
NOME_DA_COLUNA: dict[str, str] = {
    "CO_UF": "NO_UF",
    "CO_REGIAO_GEOG_INTERM": "NO_REGIAO_GEOG_INTERM",
    "CO_MESORREGIAO": "NO_MESORREGIAO",
    "CO_REGIAO_GEOG_IMED": "NO_REGIAO_GEOG_IMED",
    "CO_MICRORREGIAO": "NO_MICRORREGIAO",
    "CO_MUNICIPIO": "NO_MUNICIPIO",
}

#: R1 — o caminho da URL vira filtro de linhas. ``paises/BR`` não filtra nada.
ESCOPO_PARA_COLUNA: dict[str, str] = {
    "estados": "CO_UF",
    "municipios": "CO_MUNICIPIO",
}

#: O formato que a API devolve como GeoJSON. Sem ele a resposta vem noutra
#: representação e o erro só apareceria na hora de desenhar (R9.1).
FORMATO_GEOJSON = "application/vnd.geo+json"

#: Acima disto, o gerador avisa que a malha está cara (R9.3). Medido: as 63
#: microrregiões de SP são 21,7 KiB gzipadas em ``qualidade=minima`` e
#: 416 KiB em ``maxima`` — 19x, pelos mesmos polígonos.
LIMITE_MALHA_BYTES = 1_500_000

#: Sigla -> código do IBGE, para aceitar tanto ``/estados/SP`` quanto ``/35``.
SIGLA_PARA_CODIGO: dict[str, int] = {sigla: codigo for sigla, (codigo, _, _) in UFS.items()}


class ConsultaInvalida(ValueError):
    """A combinação pedida não pode ser respondida — com o motivo em texto."""


@dataclass(frozen=True)
class Recorte:
    """O que a URL da malha diz sobre o recorte espacial (R1 e R2)."""

    url: str
    escopo: str
    codigo: str
    intrarregiao: str | None
    qualidade: str
    coluna: str
    coluna_filtro: str | None = None
    valor_filtro: int | None = None
    coluna_nome: str | None = field(default=None)

    @property
    def rotulo(self) -> str:
        """Como o recorte aparece no nome do arquivo e no título."""
        return f"{self.intrarregiao or 'total'}-{self.codigo}".lower()


def normalizar_url(url: str) -> str:
    """Garante ``formato=application/vnd.geo+json`` na URL (R9.1)."""
    partes = urlparse(url)
    query = dict(parse_qsl(partes.query))
    query.setdefault("formato", FORMATO_GEOJSON)
    # safe=: o `/` e o `+` de application/vnd.geo+json não precisam de escape,
    # e escapá-los deixaria a URL irreconhecível em consultas.txt — que é um
    # arquivo para ler e editar à mão.
    return urlunparse(partes._replace(query=urlencode(query, safe="/+:")))


def analisar_url(url: str) -> Recorte:
    """Lê a URL do IBGE e devolve o recorte que ela descreve.

    Ergue :class:`ConsultaInvalida` com instrução quando a URL não serve — em
    especial no caso mais comum de erro, a URL sem aspas no shell, que chega
    aqui truncada no primeiro ``&`` (R9.4).
    """
    partes = urlparse(url)
    if partes.scheme not in {"http", "https"} or "servicodados.ibge.gov.br" not in partes.netloc:
        raise ConsultaInvalida(
            f"Não parece uma URL de malha do IBGE: {url}\n"
            "Esperado algo como https://servicodados.ibge.gov.br/api/v3/malhas/estados/35?..."
        )

    caminho = [p for p in partes.path.split("/") if p]
    if "malhas" not in caminho or len(caminho) < caminho.index("malhas") + 3:
        raise ConsultaInvalida(
            f"URL de malha sem escopo reconhecível: {url}\n"
            "Esperado .../malhas/paises/BR, .../malhas/estados/35 ou .../malhas/municipios/3550308"
        )
    i = caminho.index("malhas")
    escopo, codigo = caminho[i + 1], caminho[i + 2]

    query = dict(parse_qsl(partes.query))
    if "qualidade" not in query and "intrarregiao" not in query:
        # Sintoma clássico da URL sem aspas: o shell cortou tudo a partir do
        # primeiro `&`, e sobrou só `?formato=...`.
        raise ConsultaInvalida(
            f"A URL chegou sem os parâmetros esperados: {url}\n"
            "Se você a digitou no terminal, ponha entre aspas — o `&` da URL "
            'faz o shell cortar o comando: make map QT_MAT_BAS "https://..."'
        )

    intrarregiao = (query.get("intrarregiao") or "").lower() or None
    if intrarregiao is not None and intrarregiao not in NIVEIS:
        raise ConsultaInvalida(
            f"intrarregiao={intrarregiao} não é um grão que eu saiba agregar.\n"
            f"Conhecidos: {', '.join(sorted(NIVEIS))}"
        )

    if intrarregiao:
        coluna = NIVEIS[intrarregiao]
    elif escopo == "estados":
        coluna = "CO_UF"  # a malha é um polígono só: a própria UF
    elif escopo == "municipios":
        coluna = "CO_MUNICIPIO"
    else:
        raise ConsultaInvalida(
            "Sem intrarregiao=, a malha do país é um polígono só e o mapa não "
            "diz nada. Acrescente, por exemplo, &intrarregiao=UF"
        )

    filtro_coluna = ESCOPO_PARA_COLUNA.get(escopo)
    filtro_valor: int | None = None
    if filtro_coluna:
        bruto = codigo.upper()
        filtro_valor = SIGLA_PARA_CODIGO.get(bruto, None)
        if filtro_valor is None:
            if not bruto.isdigit():
                raise ConsultaInvalida(f"Não reconheço o código de {escopo}: {codigo}")
            filtro_valor = int(bruto)

    return Recorte(
        url=normalizar_url(url),
        escopo=escopo,
        codigo=str(filtro_valor) if filtro_valor is not None else codigo.upper(),
        intrarregiao=intrarregiao,
        qualidade=query.get("qualidade", "intermediaria"),
        coluna=coluna,
        coluna_filtro=filtro_coluna,
        valor_filtro=filtro_valor,
        coluna_nome=NOME_DA_COLUNA.get(coluna),
    )


# --------------------------------------------------------------------------
# A malha (cache)
# --------------------------------------------------------------------------


def dir_cache(paths: Paths | None = None) -> Path:
    """Onde as malhas baixadas ficam. Está no ``.gitignore``: é download bruto."""
    return (paths or get_paths()).data / "cache" / "malhas"


def caminho_malha(url: str, *, paths: Paths | None = None) -> Path:
    """Cache endereçado pelo hash da URL (R9.2).

    A URL normalizada é a identidade do arquivo: mesma URL, mesmo arquivo, e
    reassar o site inteiro não depende da API do IBGE estar no ar.
    """
    sha = hashlib.sha1(normalizar_url(url).encode()).hexdigest()[:16]
    return dir_cache(paths) / f"{sha}.json"


def baixar_malha(url: str, *, paths: Paths | None = None, forcar: bool = False) -> Path:
    """Baixa a malha (ou devolve a do cache)."""
    destino = caminho_malha(url, paths=paths)
    if destino.exists() and not forcar:
        return destino

    import requests

    destino.parent.mkdir(parents=True, exist_ok=True)
    resposta = requests.get(normalizar_url(url), timeout=300)
    if resposta.status_code != 200:
        raise ConsultaInvalida(
            f"O IBGE respondeu {resposta.status_code} para {url}\n{resposta.text[:300]}"
        )
    try:
        geojson = resposta.json()
    except ValueError as erro:  # pragma: no cover - depende da API
        raise ConsultaInvalida(f"A resposta do IBGE não é JSON: {erro}") from erro
    if geojson.get("type") != "FeatureCollection":
        raise ConsultaInvalida(
            "A resposta não é um FeatureCollection — confira o parâmetro formato="
        )
    destino.write_text(json.dumps(geojson), encoding="utf-8")
    return destino


# --------------------------------------------------------------------------
# A agregação
# --------------------------------------------------------------------------


def agregacao_de(variavel: str) -> str:
    """R4 — a natureza da variável decide o que fazer com ela.

    Quem classifica é o mesmo :func:`esquema.natureza` que monta o dicionário
    de dados: contagem soma, indicador vira taxa, categórica vira participação
    de uma categoria. O resto não é mapeável.
    """
    natureza = esquema.natureza(variavel)
    if natureza == "contagem":
        return "soma"
    if natureza == "indicador (0/1)":
        return "taxa"
    if natureza == "categórica codificada":
        return "categoria"
    raise ConsultaInvalida(
        f"{variavel} é do tipo '{natureza or 'desconhecido'}' e não vira mapa.\n"
        "Mapeáveis: QT_* (soma), IN_* (% de escolas), TP_* (% de uma categoria).\n"
        "Veja as opções com: censo colunas <ano> --filtro QT_"
    )


def anos_utilizaveis(
    variavel: str,
    recorte: Recorte,
    anos: list[int] | None,
    *,
    paths: Paths | None = None,
) -> list[int]:
    """R5 — só sobram os anos em que a variável *e* a coluna agrupadora existem."""
    paths = paths or get_paths()
    disponiveis = anos if anos else esquema.anos_disponiveis(paths=paths)
    if not disponiveis:
        raise ConsultaInvalida("Nenhum ano extraído em data/interim/.\nRode: censo obter <ano>")

    servem: list[int] = []
    recusas: list[str] = []
    for ano in sorted(disponiveis):
        colunas = set(loading.colunas_disponiveis(ano, paths=paths))
        faltando = [c for c in (variavel, recorte.coluna) if c not in colunas]
        if faltando:
            recusas.append(f"{ano}: sem {', '.join(faltando)}")
        else:
            servem.append(ano)

    if not servem:
        raise ConsultaInvalida(
            f"Nenhum ano serve para {variavel} por {recorte.coluna}:\n  "
            + "\n  ".join(recusas)
        )
    if anos and recusas:
        raise ConsultaInvalida(
            "Anos pedidos que não servem:\n  " + "\n  ".join(recusas)
            + f"\nAnos que serviriam: {', '.join(str(a) for a in servem)}"
        )
    # Sem anos pedidos: o mais recente que serve é o padrão razoável.
    return servem if anos else servem[-1:]


def agregar(
    variavel: str,
    recorte: Recorte,
    anos: list[int],
    *,
    categoria: int | None = None,
    paths: Paths | None = None,
) -> pd.DataFrame:
    """Devolve uma linha por (área, ano), com ``valor`` e ``escolas``.

    O empilhamento dos anos é o :func:`loading.carregar_anos` que já existe —
    é ele quem traz ``NU_ANO_CENSO`` para o DataFrame (R5).
    """
    paths = paths or get_paths()
    modo = agregacao_de(variavel)
    if modo == "categoria" and categoria is None:
        rotulos = MAPAS_DE_CODIGOS.get(variavel, {})
        opcoes = ", ".join(f"{k}={v}" for k, v in rotulos.items()) or "veja o dicionário"
        raise ConsultaInvalida(
            f"{variavel} é categórica: diga qual categoria pintar com CATEGORIA=<código>.\n"
            f"Opções: {opcoes}"
        )

    colunas = {
        "NU_ANO_CENSO",
        "TP_SITUACAO_FUNCIONAMENTO",
        recorte.coluna,
        variavel,
    }
    if recorte.coluna_nome:
        colunas.add(recorte.coluna_nome)
    if recorte.coluna_filtro:
        colunas.add(recorte.coluna_filtro)

    # apenas_ativas=True (o padrão) é o certo para mapa: escola paralisada ou
    # extinta ainda consta no arquivo, e contá-la infla o mapa.
    df = loading.carregar_anos(anos, colunas=sorted(colunas), paths=paths)

    if recorte.coluna_filtro and recorte.valor_filtro is not None:
        df = df[df[recorte.coluna_filtro] == recorte.valor_filtro]
    if df.empty:
        raise ConsultaInvalida(
            f"Nenhuma escola em {recorte.escopo}/{recorte.codigo} nos anos pedidos."
        )

    chaves = ["NU_ANO_CENSO", recorte.coluna]
    grupos = df.groupby(chaves, observed=True)
    if modo == "soma":
        valor = grupos[variavel].sum(min_count=1)
    elif modo == "taxa":
        valor = grupos[variavel].mean() * 100
    else:
        valor = grupos[variavel].apply(lambda s: (s == categoria).mean() * 100)

    saida = valor.reset_index(name="valor")
    saida["escolas"] = grupos.size().reset_index(name="n")["n"]
    if recorte.coluna_nome:
        nomes = grupos[recorte.coluna_nome].first().reset_index()
        saida["nome"] = nomes[recorte.coluna_nome]
    else:
        saida["nome"] = saida[recorte.coluna].astype(str)
    saida["codarea"] = saida[recorte.coluna].astype("Int64").astype(str)
    return saida.rename(columns={"NU_ANO_CENSO": "ano"})[
        ["ano", "codarea", "nome", "valor", "escolas"]
    ]


# --------------------------------------------------------------------------
# O produto: GeoJSON com o dado dentro (R7)
# --------------------------------------------------------------------------


def unir(malha: dict, dados: pd.DataFrame, meta: dict) -> tuple[dict, dict]:
    """Funde geometria e dado num único GeoJSON; devolve também a cobertura.

    A cobertura é relatada, não presumida (R3): um mapa com buracos
    silenciosos é pior que um erro.
    """
    por_area: dict[str, dict] = {}
    for linha in dados.itertuples(index=False):
        entrada = por_area.setdefault(
            linha.codarea, {"nome": linha.nome, "valores": {}, "escolas": {}}
        )
        entrada["valores"][str(linha.ano)] = (
            None if pd.isna(linha.valor) else round(float(linha.valor), 2)
        )
        entrada["escolas"][str(linha.ano)] = int(linha.escolas)

    feicoes = []
    com_dado = 0
    for feicao in malha.get("features", []):
        codarea = str(feicao.get("properties", {}).get("codarea", ""))
        dado = por_area.get(codarea)
        if dado:
            com_dado += 1
        feicao["properties"] = {
            "codarea": codarea,
            "nome": (dado or {}).get("nome", codarea),
            "valores": (dado or {}).get("valores", {}),
            "escolas": (dado or {}).get("escolas", {}),
        }
        feicoes.append(feicao)

    sem_poligono = sorted(set(por_area) - {f["properties"]["codarea"] for f in feicoes})
    cobertura = {
        "areas_na_malha": len(feicoes),
        "areas_com_dado": com_dado,
        "codigos_sem_poligono": sem_poligono[:20],
        "n_codigos_sem_poligono": len(sem_poligono),
    }
    return {
        "type": "FeatureCollection",
        "features": feicoes,
        "meta": {**meta, "cobertura": cobertura},
    }, cobertura


def slug(variavel: str, recorte: Recorte, anos: list[int]) -> str:
    """R6 — nome determinístico: reassar sobrescreve, não acumula lixo."""
    faixa = f"{anos[0]}-{anos[-1]}" if len(anos) > 1 else str(anos[0])
    cru = f"{variavel}-{recorte.rotulo}-{faixa}".lower()
    sem_acento = unicodedata.normalize("NFKD", cru).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9-]+", "-", sem_acento).strip("-")


def titulo_padrao(variavel: str, recorte: Recorte, anos: list[int]) -> str:
    grao = (recorte.intrarregiao or "área").replace("-", " ")
    onde = "Brasil" if recorte.escopo == "paises" else f"{recorte.escopo[:-1]} {recorte.codigo}"
    faixa = f"{anos[0]}–{anos[-1]}" if len(anos) > 1 else str(anos[0])
    return f"{variavel} por {grao} — {onde}, {faixa}"


def descricao_oficial(variavel: str, anos: list[int], *, paths: Paths | None = None) -> str:
    """A descrição do INEP para a variável, se o dicionário do ZIP estiver por perto."""
    try:
        tabela = esquema.descricoes(anos, paths=paths)
    except Exception:  # pragma: no cover - o anexo pode não existir no ZIP
        return ""
    if tabela.empty or "coluna" not in tabela.columns:
        return ""
    achou = tabela[tabela["coluna"] == variavel]
    if achou.empty:
        return ""
    return str(achou.iloc[0].get("descricao", "") or "")


# --------------------------------------------------------------------------
# A orquestração: do comando à página
# --------------------------------------------------------------------------


def gerar_mapa(
    variavel: str,
    url: str,
    *,
    anos: list[int] | None = None,
    categoria: int | None = None,
    titulo: str | None = None,
    paths: Paths | None = None,
    forcar_malha: bool = False,
) -> dict:
    """Assa um mapa inteiro: dados, GeoJSON, página e registro da consulta.

    Devolve um dicionário com o que foi produzido — os caminhos, a cobertura
    da junção e os avisos —, que é o que o CLI imprime e o índice consome.
    """
    from censo_escolar import sitio

    paths = (paths or get_paths()).criar()
    variavel = variavel.upper()
    recorte = analisar_url(url)
    modo = agregacao_de(variavel)
    usar = anos_utilizaveis(variavel, recorte, anos, paths=paths)

    dados = agregar(variavel, recorte, usar, categoria=categoria, paths=paths)
    caminho = baixar_malha(recorte.url, paths=paths, forcar=forcar_malha)
    malha = json.loads(caminho.read_text(encoding="utf-8"))

    nome = slug(variavel, recorte, usar)
    descricao = descricao_oficial(variavel, usar, paths=paths)
    unidade = " %" if modo in {"taxa", "categoria"} else ""
    geojson, cobertura = unir(
        malha,
        dados,
        {
            "variavel": variavel,
            "descricao": descricao,
            "natureza": esquema.natureza(variavel),
            "agregacao": modo,
            "categoria": categoria,
            "anos": usar,
            "grao": recorte.intrarregiao or recorte.escopo,
            "fonte_malha": recorte.url,
            "gerado_em": date.today().isoformat(),
        },
    )

    destino_dados = sitio.dir_site(paths) / "dados" / f"{nome}.geojson"
    destino_dados.parent.mkdir(parents=True, exist_ok=True)
    destino_dados.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    # O CSV agregado sai do mesmo comando que o GeoJSON, de propósito: é a
    # tabela que produziu o mapa, conferível no Calc ou no `censo amostra`. Se
    # o número do mapa parecer errado, ela está ali do lado — e, saindo juntos,
    # os dois nunca divergem.
    destino_csv = paths.processed / f"{nome}.csv"
    dados.to_csv(destino_csv, index=False)

    avisos = _avisos(destino_dados, cobertura, usar, variavel, paths=paths)
    sitio.garantir_vendor(paths=paths)
    pagina = sitio.escrever_pagina(
        nome,
        titulo=titulo or titulo_padrao(variavel, recorte, usar),
        subtitulo=_subtitulo(modo, categoria, variavel, cobertura),
        descricao=descricao,
        rodape=_rodape(variavel, recorte, usar, avisos),
        anos=usar,
        unidade=unidade,
        paths=paths,
    )
    consulta = sitio.Consulta(
        variavel=variavel,
        url=recorte.url,
        anos=usar if anos else [],
        opcoes=({"CATEGORIA": str(categoria)} if categoria is not None else {})
        | ({"TITULO": titulo} if titulo else {}),
    )
    sitio.registrar_consulta(consulta, paths=paths)

    return {
        "slug": nome,
        "titulo": titulo or titulo_padrao(variavel, recorte, usar),
        "descricao": descricao,
        "variavel": variavel,
        "anos": usar,
        "grao": recorte.intrarregiao or recorte.escopo,
        "areas": cobertura["areas_na_malha"],
        "dados": destino_dados,
        "csv": destino_csv,
        "pagina": pagina,
        "cobertura": cobertura,
        "avisos": avisos,
    }


def _avisos(
    destino: Path, cobertura: dict, anos: list[int], variavel: str, *, paths: Paths
) -> list[str]:
    avisos: list[str] = []
    faltando = cobertura["areas_na_malha"] - cobertura["areas_com_dado"]
    if faltando:
        avisos.append(f"{faltando} área(s) da malha ficaram sem dado")
    if cobertura["n_codigos_sem_poligono"]:
        avisos.append(
            f"{cobertura['n_codigos_sem_poligono']} código(s) do censo não acharam polígono "
            "(municípios criados ou extintos entre edições costumam explicar)"
        )
    if destino.stat().st_size > LIMITE_MALHA_BYTES:
        avisos.append(
            f"o arquivo saiu com {destino.stat().st_size / 1_048_576:.1f} MiB — "
            "considere qualidade=minima na URL, ou um recorte menor"
        )
    return avisos


def _subtitulo(modo: str, categoria: int | None, variavel: str, cobertura: dict) -> str:
    if modo == "soma":
        return "Soma da variável por área, escolas em atividade"
    if modo == "taxa":
        return "Percentual das escolas em atividade da área"
    rotulo = MAPAS_DE_CODIGOS.get(variavel, {}).get(categoria, categoria)
    return f"Percentual de escolas com {variavel} = {rotulo}"


def _rodape(variavel: str, recorte: Recorte, anos: list[int], avisos: list[str]) -> str:
    faixa = ", ".join(str(a) for a in anos)
    linhas = [
        f"<p>Variável <code>{variavel}</code> · anos {faixa} · "
        f"malha: <a href=\"{recorte.url}\">IBGE</a> "
        f"({recorte.intrarregiao or recorte.escopo}, qualidade {recorte.qualidade}).</p>",
        "<p>Fonte: microdados do Censo Escolar da Educação Básica (INEP). "
        "Só escolas em atividade (<code>TP_SITUACAO_FUNCIONAMENTO = 1</code>).</p>",
    ]
    if avisos:
        linhas.append("<p><strong>Ressalvas:</strong> " + "; ".join(avisos) + ".</p>")
    return "\n  ".join(linhas)


def reassar_tudo(*, paths: Paths | None = None) -> list[dict]:
    """Relê ``site/consultas.txt`` e regenera todos os mapas e o índice."""
    from censo_escolar import sitio

    paths = paths or get_paths()
    consultas = sitio.ler_consultas(paths=paths)
    resultados: list[dict] = []
    for consulta in consultas:
        categoria = consulta.opcoes.get("CATEGORIA")
        resultados.append(
            gerar_mapa(
                consulta.variavel,
                consulta.url,
                anos=consulta.anos or None,
                categoria=int(categoria) if categoria else None,
                titulo=consulta.opcoes.get("TITULO"),
                paths=paths,
            )
        )
    sitio.escrever_indice([sitio.entrada_de_indice(r) for r in resultados], paths=paths)
    sitio.gerar_index([sitio.entrada_de_indice(r) for r in resultados], paths=paths)
    return resultados


#: Os grãos que o `censo malhas` baixa por padrão — os de país inteiro, que
#: servem a qualquer recorte nacional. A municipal fica de fora do padrão por
#: ser a mais pesada (817 KiB gzipados contra 28 KiB da de UF).
MALHAS_PADRAO: tuple[str, ...] = ("UF", "regiao-intermediaria", "regiao-imediata")

URL_BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"


def url_para(
    nivel: str,
    *,
    escopo: str = "paises",
    codigo: str = "BR",
    qualidade: str = "minima",
) -> str:
    """Monta a URL canônica de uma malha — o mesmo endereço que se digitaria."""
    return normalizar_url(
        f"{URL_BASE}/{escopo}/{codigo}?intrarregiao={nivel}&qualidade={qualidade}"
    )


def preaquecer(
    niveis: list[str] | None = None,
    *,
    ufs: list[str] | None = None,
    paths: Paths | None = None,
) -> list[tuple[Path, str]]:
    """Baixa malhas para o cache, para quem vai trabalhar sem rede depois.

    É conveniência, não obrigação: o ``censo map`` baixa o que faltar. As
    malhas ficam em ``data/cache/malhas/``, que está no ``.gitignore`` — o que
    é publicado é o GeoJSON recortado com o dado dentro.
    """
    baixadas = []
    for nivel in niveis or MALHAS_PADRAO:
        url = url_para(nivel)
        baixadas.append((baixar_malha(url, paths=paths), url))
    for uf in ufs or []:
        url = url_para("municipio", escopo="estados", codigo=uf.upper())
        baixadas.append((baixar_malha(url, paths=paths), url))
    return baixadas
