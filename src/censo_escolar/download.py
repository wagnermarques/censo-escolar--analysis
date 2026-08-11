"""Download e extração dos microdados do Censo Escolar."""

from __future__ import annotations

import os
import shutil
import ssl
import zipfile
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from censo_escolar.config import (
    ENV_CA_BUNDLE,
    URL_CA_INTERMEDIARIA,
    URL_MICRODADOS,
    Paths,
    get_paths,
)


class AnoIndisponivel(FileNotFoundError):
    """O INEP não publica (ainda) os microdados do ano pedido.

    Herda de ``FileNotFoundError`` de propósito: para quem chama, "esse ano não
    existe na origem" é o mesmo tipo de problema que "esse ZIP não está no
    disco", e quem já trata um trata o outro.
    """


#: Tamanho do bloco de leitura no download em streaming.
_CHUNK = 1 << 20  # 1 MiB

#: O servidor do INEP derruba a primeira conexão com alguma frequência (RST
#: durante o handshake TLS). Não é erro do cliente: a segunda tentativa quase
#: sempre passa. Por isso todo acesso à rede aqui vai por uma sessão com
#: retentativa e backoff, em vez de estourar um traceback na cara do usuário.
_TENTATIVAS = 5


def url_do_ano(ano: int, url: str | None = None) -> str:
    """Monta a URL do ZIP de microdados para ``ano``."""
    return (url or URL_MICRODADOS).format(ano=ano)


def _sessao(tentativas: int = _TENTATIVAS) -> requests.Session:
    """Sessão HTTP com retentativa em erros de conexão e em 5xx."""
    politica = Retry(
        total=tentativas,
        connect=tentativas,
        read=tentativas,
        status=tentativas,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    sessao = requests.Session()
    adaptador = HTTPAdapter(max_retries=politica)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)
    return sessao


def caminho_ca_bundle(paths: Paths | None = None) -> Path:
    """Onde o bundle de CAs do projeto é gravado."""
    paths = paths or get_paths()
    return paths.certs / "inep-ca.pem"


def preparar_ca_bundle(
    *,
    paths: Paths | None = None,
    url: str | None = None,
    forcar: bool = False,
) -> Path:
    """Monta o bundle de CAs que valida o certificado do INEP.

    O servidor do INEP manda apenas o certificado folha e omite a CA
    intermediária, então nem o certifi nem o armazenamento do sistema
    conseguem fechar a cadeia até a raiz GlobalSign. Aqui baixamos essa
    intermediária e a concatenamos ao bundle do certifi.

    Isso mantém a verificação TLS ligada — o contrário de ``verify=False``,
    que desligaria a checagem inteira para contornar um certificado só.
    """
    import certifi

    paths = paths or get_paths()
    destino = caminho_ca_bundle(paths)
    if destino.exists() and not forcar:
        return destino

    resposta = _sessao().get(url or URL_CA_INTERMEDIARIA, timeout=30)
    resposta.raise_for_status()
    bruto = resposta.content

    # O GlobalSign serve DER; aceitamos PEM também, caso a URL mude.
    if b"-----BEGIN CERTIFICATE-----" in bruto:
        intermediaria = bruto.decode("ascii")
    else:
        intermediaria = ssl.DER_cert_to_PEM_cert(bruto)

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        Path(certifi.where()).read_text(encoding="utf-8") + "\n" + intermediaria,
        encoding="utf-8",
    )
    return destino


def ca_bundle(paths: Paths | None = None) -> str | bool:
    """Valor de ``verify`` para o ``requests``.

    Ordem: variável de ambiente, bundle do projeto, padrão do ``requests``
    (certifi). Nunca devolve ``False`` — se nada estiver disponível,
    tentamos a verificação normal e deixamos o erro aparecer.
    """
    env = os.environ.get(ENV_CA_BUNDLE)
    if env:
        return env
    bundle = caminho_ca_bundle(paths)
    if bundle.exists():
        return str(bundle)
    return True


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
    sessao = _sessao()
    verificar = ca_bundle(paths)

    def abrir():
        return sessao.get(endereco, stream=True, timeout=timeout, verify=verificar)

    try:
        resposta = abrir()
    except requests.exceptions.SSLError:
        # Cadeia incompleta do lado do INEP: monta o bundle e tenta de novo.
        # Só faz sentido uma vez; se falhar outra vez, o erro sobe.
        print("Cadeia de certificados incompleta; baixando a CA intermediária…")
        verificar = str(preparar_ca_bundle(paths=paths, forcar=True))
        resposta = abrir()

    with resposta:
        # 404 quase nunca é defeito: é o ano que ainda não foi publicado. Um
        # traceback de `raise_for_status` para dizer isso seria desproporcional.
        if resposta.status_code == 404:
            raise AnoIndisponivel(
                f"O INEP não tem microdados de {ano} em {endereco} (HTTP 404).\n"
                f"Os microdados de um ano costumam sair no ano seguinte ao da coleta; "
                f"confira os anos publicados em https://www.gov.br/inep/ "
                f"(Dados Abertos > Microdados).\n"
                f"Se o endereço é que mudou, passe --url (use {{ano}} como marcador) "
                f"ou defina CENSO_ESCOLAR_URL."
            )
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
