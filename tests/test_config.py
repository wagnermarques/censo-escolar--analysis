"""Testes da resolução de caminhos — o que garante que org-babel e Jupyter
enxerguem os mesmos diretórios, independentemente do cwd."""

from __future__ import annotations

import os
from pathlib import Path

from censo_escolar import config


def test_raiz_independe_do_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    esperado = Path(config.__file__).resolve().parents[2]
    assert config.encontrar_raiz() == esperado


def test_variavel_de_ambiente_sobrepoe(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_RAIZ, str(tmp_path))
    assert config.encontrar_raiz() == tmp_path.resolve()


def test_diretorio_de_dados_customizado(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_DATA, str(tmp_path / "externo"))
    paths = config.get_paths()
    assert paths.raw == (tmp_path / "externo" / "raw").resolve()


def test_criar_cria_os_diretorios(tmp_path):
    paths = config.get_paths(tmp_path).criar()
    for p in (paths.raw, paths.interim, paths.processed, paths.figures):
        assert p.is_dir()


def test_url_usa_o_marcador_de_ano(monkeypatch):
    from censo_escolar import download

    monkeypatch.setattr(download, "URL_MICRODADOS", "http://x/{ano}.zip")
    assert download.url_do_ano(2023) == "http://x/2023.zip"
    assert download.url_do_ano(2023, "http://y/{ano}") == "http://y/2023"


def test_paths_sao_absolutos():
    paths = config.get_paths()
    assert all(Path(v).is_absolute() for v in vars(paths).values())
    assert os.path.isabs(paths.notebooks)
