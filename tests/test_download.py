"""Testes da camada de rede: retentativa e resolução do bundle de CAs.

Nada aqui toca a rede de verdade — o servidor do INEP é justamente a parte
instável que motivou este código.
"""

from __future__ import annotations

import ssl

import pytest
import requests

from censo_escolar import download
from censo_escolar.config import ENV_CA_BUNDLE, get_paths


def test_sessao_tem_retentativa_nos_dois_esquemas():
    sessao = download._sessao(tentativas=3)
    for esquema in ("https://", "http://"):
        politica = sessao.get_adapter(esquema).max_retries
        assert politica.total == 3
        assert politica.connect == 3  # o RST do INEP é erro de conexão
        assert politica.backoff_factor > 0


def test_ca_bundle_prefere_a_variavel_de_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CA_BUNDLE, str(tmp_path / "meu.pem"))
    assert download.ca_bundle() == str(tmp_path / "meu.pem")


def test_ca_bundle_usa_o_do_projeto_quando_existe(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CA_BUNDLE, raising=False)
    paths = get_paths(tmp_path)
    bundle = download.caminho_ca_bundle(paths)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    assert download.ca_bundle(paths) == str(bundle)


def test_ca_bundle_cai_no_padrao_do_requests(tmp_path, monkeypatch):
    """Sem bundle nenhum, verificamos normalmente — nunca ``False``."""
    monkeypatch.delenv(ENV_CA_BUNDLE, raising=False)
    assert download.ca_bundle(get_paths(tmp_path)) is True


class _RespostaFalsa:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def _sessao_que_devolve(conteudo: bytes):
    """Fábrica de sessão falsa: qualquer GET devolve ``conteudo``."""

    class _Sessao:
        def get(self, *a, **k):
            return _RespostaFalsa(conteudo)

    return lambda *a, **k: _Sessao()


def _certificado_der() -> bytes:
    """Um DER qualquer; só precisamos que não seja PEM."""
    return bytes.fromhex("308201f0") + b"\x00" * 32


def test_preparar_ca_bundle_concatena_certifi_e_intermediaria(tmp_path, monkeypatch):
    import certifi

    monkeypatch.setattr(download, "_sessao", _sessao_que_devolve(_certificado_der()))
    monkeypatch.setattr(
        ssl,
        "DER_cert_to_PEM_cert",
        lambda b: "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n",
    )

    destino = download.preparar_ca_bundle(paths=get_paths(tmp_path))
    conteudo = destino.read_text(encoding="utf-8")

    assert conteudo.startswith(certifi.contents()[:64])
    assert conteudo.endswith("-----END CERTIFICATE-----\n")
    assert conteudo.count("BEGIN CERTIFICATE") == certifi.contents().count("BEGIN CERTIFICATE") + 1


def test_preparar_ca_bundle_aceita_pem_direto(tmp_path, monkeypatch):
    pem = b"-----BEGIN CERTIFICATE-----\nPEMPEM\n-----END CERTIFICATE-----\n"
    monkeypatch.setattr(download, "_sessao", _sessao_que_devolve(pem))
    destino = download.preparar_ca_bundle(paths=get_paths(tmp_path))
    assert "PEMPEM" in destino.read_text(encoding="utf-8")


def test_preparar_ca_bundle_reaproveita_o_existente(tmp_path, monkeypatch):
    paths = get_paths(tmp_path)
    bundle = download.caminho_ca_bundle(paths)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text("ja existia", encoding="utf-8")

    def explodir(*a, **k):
        raise AssertionError("não deveria ir à rede")

    monkeypatch.setattr(download, "_sessao", explodir)
    assert download.preparar_ca_bundle(paths=paths) == bundle
    assert bundle.read_text(encoding="utf-8") == "ja existia"


def test_baixar_ano_monta_o_bundle_apos_erro_de_ssl(tmp_path, monkeypatch):
    """O primeiro GET falha na cadeia; o segundo passa com o bundle novo."""
    paths = get_paths(tmp_path)
    chamadas: list[object] = []

    class _Stream:
        status_code = 200
        headers = {"Content-Length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"PK\x03\x04"

    class _Sessao:
        def get(self, url, **kwargs):
            chamadas.append(kwargs.get("verify"))
            if len(chamadas) == 1:
                raise requests.exceptions.SSLError("unable to get local issuer certificate")
            return _Stream()

    monkeypatch.setattr(download, "_sessao", lambda *a, **k: _Sessao())
    monkeypatch.setattr(
        download, "preparar_ca_bundle", lambda **k: tmp_path / "certs" / "inep-ca.pem"
    )

    destino = download.baixar_ano(2023, paths=paths)

    assert destino.read_bytes() == b"PK\x03\x04"
    assert len(chamadas) == 2
    assert chamadas[1] == str(tmp_path / "certs" / "inep-ca.pem")
    assert not destino.with_suffix(".zip.part").exists()


def _sessao_com_status(status: int):
    """Sessão falsa cujo GET devolve uma resposta com o status pedido."""

    class _Resposta:
        status_code = status
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def close(self):
            return None

        def raise_for_status(self):
            raise requests.exceptions.HTTPError(f"{status} Client Error")

    class _Sessao:
        def __init__(self):
            self.urls: list[str] = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            return _Resposta()

    sessao = _Sessao()
    return lambda *a, **k: sessao


def test_variante_com_sublinhado_e_tentada(monkeypatch):
    """O INEP publicou 2025 como ``..._2025_.zip``. Sem essa variante na lista,
    um ano que existe responde 404 e parece não existir."""
    monkeypatch.delenv("CENSO_ESCOLAR_URL", raising=False)
    urls = download.urls_do_ano(2025)
    assert urls[0].endswith("microdados_censo_escolar_2025.zip")
    assert any(u.endswith("microdados_censo_escolar_2025_.zip") for u in urls)


def test_sobreposicao_explicita_desliga_as_variantes(monkeypatch):
    monkeypatch.delenv("CENSO_ESCOLAR_URL", raising=False)
    assert download.urls_do_ano(2025, "http://x/{ano}.zip") == ("http://x/2025.zip",)


def test_ano_nao_publicado_vira_erro_explicativo(tmp_path, monkeypatch):
    """404 em *todas* as variantes é o caso de "esse ano não saiu mesmo".

    O recado precisa dizer o que foi tentado e o que fazer; um ``HTTPError``
    cru obrigaria quem chamou a decifrar um traceback para descobrir isso.
    """
    monkeypatch.delenv("CENSO_ESCOLAR_URL", raising=False)
    fabrica = _sessao_com_status(404)
    monkeypatch.setattr(download, "_sessao", fabrica)

    with pytest.raises(download.AnoIndisponivel) as erro:
        download.baixar_ano(2525, paths=get_paths(tmp_path))

    texto = str(erro.value)
    assert "2525" in texto
    assert "--url" in texto  # a saída, para quando o endereço é que mudou
    assert isinstance(erro.value, FileNotFoundError)
    # Só desiste depois de esgotar as variantes conhecidas.
    assert len(fabrica().urls) == len(download.urls_do_ano(2525))


def test_erro_http_que_nao_e_404_continua_subindo(tmp_path, monkeypatch):
    """Só o 404 tem tratamento especial; 500 é problema de verdade."""
    monkeypatch.setattr(download, "_sessao", _sessao_com_status(500))

    with pytest.raises(requests.exceptions.HTTPError):
        download.baixar_ano(2023, paths=get_paths(tmp_path))


def test_404_nao_deixa_arquivo_parcial(tmp_path, monkeypatch):
    paths = get_paths(tmp_path)
    monkeypatch.setattr(download, "_sessao", _sessao_com_status(404))

    with pytest.raises(download.AnoIndisponivel):
        download.baixar_ano(2525, paths=paths)

    assert list(paths.raw.glob("*.part")) == []
    assert list(paths.raw.glob("*.zip")) == []


def test_baixar_ano_nao_engole_erro_de_ssl_persistente(tmp_path, monkeypatch):
    """Se falhar de novo com o bundle pronto, o erro tem de subir."""
    paths = get_paths(tmp_path)

    class _Sessao:
        def get(self, url, **kwargs):
            raise requests.exceptions.SSLError("continua quebrado")

    monkeypatch.setattr(download, "_sessao", lambda *a, **k: _Sessao())
    monkeypatch.setattr(download, "preparar_ca_bundle", lambda **k: tmp_path / "b.pem")

    with pytest.raises(requests.exceptions.SSLError):
        download.baixar_ano(2023, paths=paths)
