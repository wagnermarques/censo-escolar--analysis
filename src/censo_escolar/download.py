"""Download e extração dos microdados do Censo Escolar."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import requests

from censo_escolar.config import URL_MICRODADOS, Paths, get_paths

#: Tamanho do bloco de leitura no download em streaming.
_CHUNK = 1 << 20  # 1 MiB


def url_do_ano(ano: int, url: str | None = None) -> str:
    """Monta a URL do ZIP de microdados para ``ano``."""
    return (url or URL_MICRODADOS).format(ano=ano)


def baixar_ano(
    ano: int,
    *,
    url: str | None = None,
    paths: Paths | None = None,
    forcar: bool = False,
    timeout: int = 60,
) -> Path:
    """Baixa o ZIP de microdados de ``ano`` para ``data/raw/``.

    Se o arquivo já existir e ``forcar`` for ``False``, o download é pulado.
    Escreve primeiro em ``.part`` e só então renomeia, para que uma
    interrupção não deixe um ZIP truncado passando por completo.
    """
    paths = (paths or get_paths()).criar()
    destino = paths.raw / f"microdados_censo_escolar_{ano}.zip"
    if destino.exists() and not forcar:
        return destino

    endereco = url_do_ano(ano, url)
    parcial = destino.with_suffix(".zip.part")
    with requests.get(endereco, stream=True, timeout=timeout) as resposta:
        resposta.raise_for_status()
        total = int(resposta.headers.get("Content-Length", 0))
        baixado = 0
        with parcial.open("wb") as saida:
            for bloco in resposta.iter_content(chunk_size=_CHUNK):
                saida.write(bloco)
                baixado += len(bloco)
                if total:
                    print(f"\r  {baixado / total:6.1%}  ({baixado >> 20} MiB)", end="")
        if total:
            print()
    parcial.replace(destino)
    return destino


def extrair_ano(
    ano: int,
    *,
    paths: Paths | None = None,
    forcar: bool = False,
) -> Path:
    """Extrai o ZIP de ``ano`` em ``data/interim/microdados_censo_escolar_<ano>/``."""
    paths = (paths or get_paths()).criar()
    zip_path = paths.raw / f"microdados_censo_escolar_{ano}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(
            f"ZIP não encontrado: {zip_path}\n"
            f"Rode primeiro: censo baixar {ano}   (ou baixe manualmente do site do INEP)"
        )

    destino = paths.interim / f"microdados_censo_escolar_{ano}"
    if destino.exists():
        if not forcar:
            return destino
        shutil.rmtree(destino)

    temporario = destino.with_name(destino.name + ".tmp")
    if temporario.exists():
        shutil.rmtree(temporario)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(temporario)

    # O ZIP do INEP costuma trazer um único diretório-raiz interno. Quando é o
    # caso, promovemos esse diretório para evitar um nível redundante.
    filhos = list(temporario.iterdir())
    if len(filhos) == 1 and filhos[0].is_dir():
        filhos[0].replace(destino)
        temporario.rmdir()
    else:
        temporario.replace(destino)
    return destino


def obter_ano(ano: int, *, url: str | None = None, paths: Paths | None = None) -> Path:
    """Baixa (se preciso) e extrai o ano; devolve o diretório extraído."""
    baixar_ano(ano, url=url, paths=paths)
    return extrair_ano(ano, paths=paths)
