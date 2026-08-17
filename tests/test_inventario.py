"""Testes do inventário: o que o disco diz sobre cada ano.

Os estados que interessam não são só "tem" e "não tem" — o meio do caminho é
que confunde na hora de retomar o trabalho: download interrompido, diretório
extraído sem o CSV dentro, Parquet sem o CSV que o gerou.
"""

from __future__ import annotations

from censo_escolar import inventario
from censo_escolar.config import get_paths


def _projeto(tmp_path):
    """Um projeto vazio, com os diretórios de dados já criados."""
    return get_paths(tmp_path).criar()


def _baixar(paths, ano: int, conteudo: bytes = b"zip") -> None:
    (paths.raw / f"microdados_censo_escolar_{ano}.zip").write_bytes(conteudo)


def _extrair(paths, ano: int, *, com_csv: bool = True) -> None:
    destino = paths.interim / f"microdados_censo_escolar_{ano}" / "dados"
    destino.mkdir(parents=True)
    if com_csv:
        (destino / f"microdados_ed_basica_{ano}.csv").write_text("NU_ANO_CENSO\n", encoding="utf-8")


def test_projeto_vazio_nao_lista_nada(tmp_path):
    assert inventario.inventariar(paths=_projeto(tmp_path)) == []


def test_lista_os_anos_em_ordem(tmp_path):
    paths = _projeto(tmp_path)
    for ano in (2024, 2019, 2023):
        _baixar(paths, ano)
    assert [i.ano for i in inventario.inventariar(paths=paths)] == [2019, 2023, 2024]


def test_ano_so_baixado_nao_esta_completo(tmp_path):
    paths = _projeto(tmp_path)
    _baixar(paths, 2023)
    (item,) = inventario.inventariar(paths=paths)
    assert item.zip is not None
    assert item.extraido is None
    assert item.completo is False


def test_ano_extraido_localiza_o_csv(tmp_path):
    paths = _projeto(tmp_path)
    _baixar(paths, 2023)
    _extrair(paths, 2023)
    (item,) = inventario.inventariar(paths=paths)
    assert item.csv.name == "microdados_ed_basica_2023.csv"
    assert item.completo is True


def test_extracao_pela_metade_aparece_incompleta(tmp_path):
    """O diretório existir não basta: sem o CSV, o ano não serve para análise."""
    paths = _projeto(tmp_path)
    _baixar(paths, 2023)
    _extrair(paths, 2023, com_csv=False)
    (item,) = inventario.inventariar(paths=paths)
    assert item.extraido is not None
    assert item.csv is None
    assert item.completo is False
    assert "não encontrado" in inventario.formatar([item], paths=paths)


def test_download_interrompido_aparece_como_parcial(tmp_path):
    paths = _projeto(tmp_path)
    (paths.raw / "microdados_censo_escolar_2025.zip.part").write_bytes(b"metade")
    (item,) = inventario.inventariar(paths=paths)
    assert item.zip is None
    assert item.parcial is not None
    assert "parcial" in inventario.formatar([item], paths=paths)


def test_parcial_some_quando_o_zip_completo_chega(tmp_path):
    """O ``.part`` sobrevivente de uma tentativa anterior não vira ruído."""
    paths = _projeto(tmp_path)
    _baixar(paths, 2025)
    (paths.raw / "microdados_censo_escolar_2025.zip.part").write_bytes(b"resto")
    (item,) = inventario.inventariar(paths=paths)
    assert item.zip is not None
    assert item.parcial is None


def test_parquet_sozinho_ainda_lista_o_ano(tmp_path):
    """Apagar o ZIP e ficar só com o Parquet é comum — e continua sendo um dado."""
    paths = _projeto(tmp_path)
    (paths.processed / "escolas_2023.parquet").write_bytes(b"parquet")
    (item,) = inventario.inventariar(paths=paths)
    assert item.ano == 2023
    assert item.parquet is not None
    assert item.zip is None


def test_formatar_sem_nada_ensina_o_proximo_passo(tmp_path):
    saida = inventario.formatar([], paths=_projeto(tmp_path))
    assert "censo obter" in saida


def test_formatar_alinha_a_tabela_e_conta_o_total(tmp_path):
    paths = _projeto(tmp_path)
    _baixar(paths, 2023, b"x" * 2048)
    _extrair(paths, 2023)
    _baixar(paths, 2024, b"x" * 1024)
    saida = inventario.formatar(inventario.inventariar(paths=paths), paths=paths)
    linhas = saida.splitlines()
    assert linhas[0].startswith("ANO")
    # Cabeçalho e linhas compartilham as mesmas colunas.
    assert linhas[1].index("2.0 KiB") == linhas[0].index("ZIP")
    assert "2 ano(s) baixado(s), 1 extraído(s)" in linhas[-1]
    assert "3.0 KiB" in linhas[-1]


def test_humano_troca_de_unidade():
    assert inventario._humano(512) == "512 B"
    assert inventario._humano(1024) == "1.0 KiB"
    assert inventario._humano(5 * 1024**2) == "5.0 MiB"
    assert inventario._humano(3 * 1024**3) == "3.0 GiB"
