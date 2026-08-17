"""O que já está no disco: quais anos foram baixados, extraídos e convertidos.

O pipeline tem três estágios que deixam rastros em diretórios diferentes — o
ZIP em ``data/raw/``, os arquivos extraídos em ``data/interim/`` e o Parquet em
``data/processed/`` — e nenhum deles, sozinho, responde "o que eu já tenho?".
Depois de alguns ``censo obter`` em dias diferentes, a resposta costuma estar
espalhada em três ``ls``.

Este módulo junta os três num inventário só, por ano. Ele nunca vai à rede e
nunca lê o conteúdo dos arquivos: só olha nomes e tamanhos, para poder ser a
primeira coisa que alguém roda ao voltar ao projeto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from censo_escolar.config import Paths, get_paths
from censo_escolar.download import caminho_extraido, caminho_zip
from censo_escolar.loading import caminho_parquet, localizar_csv_escolas

#: Como o ano aparece no nome de cada artefato do pipeline. A varredura é por
#: nome porque é o que existe antes de qualquer leitura: um ano só entra no
#: inventário se deixou rastro em algum dos três diretórios.
_PADROES_ANO: tuple[tuple[str, str], ...] = (
    ("raw", r"^microdados_censo_escolar_(\d{4})\.zip(\.part)?$"),
    ("interim", r"^microdados_censo_escolar_(\d{4})$"),
    ("processed", r"^escolas_(\d{4})\.parquet$"),
)


@dataclass(frozen=True)
class Microdados:
    """O que existe no disco para um ano do Censo Escolar."""

    ano: int
    #: ZIP baixado por inteiro em ``data/raw/``.
    zip: Path | None = None
    #: ``.zip.part`` de um download interrompido — o ZIP acima ainda não existe.
    parcial: Path | None = None
    #: Diretório extraído em ``data/interim/``.
    extraido: Path | None = None
    #: CSV de escolas localizado dentro do diretório extraído.
    csv: Path | None = None
    #: Parquet de escolas em ``data/processed/``.
    parquet: Path | None = None

    @property
    def completo(self) -> bool:
        """Pronto para análise: extraído *e* com o CSV de escolas localizável.

        A distinção importa porque o diretório existir não basta — uma extração
        interrompida deixa o diretório lá, sem o arquivo que interessa.
        """
        return self.csv is not None


def inventariar(*, paths: Paths | None = None) -> list[Microdados]:
    """Levanta, ano a ano, o estado dos microdados no disco."""
    paths = paths or get_paths()
    anos: set[int] = set()
    for campo, padrao in _PADROES_ANO:
        diretorio: Path = getattr(paths, campo)
        if not diretorio.exists():
            continue
        for item in diretorio.iterdir():
            casa = re.match(padrao, item.name)
            if casa:
                anos.add(int(casa.group(1)))

    return [_estado_do_ano(ano, paths) for ano in sorted(anos)]


def _estado_do_ano(ano: int, paths: Paths) -> Microdados:
    zip_path = caminho_zip(ano, paths)
    parcial = zip_path.with_suffix(".zip.part")
    extraido = caminho_extraido(ano, paths)
    parquet = caminho_parquet(ano, paths)

    csv = None
    if extraido.is_dir():
        try:
            csv = localizar_csv_escolas(ano, paths=paths)
        except FileNotFoundError:
            # Extração pela metade, ou pacote sem CSV de escolas: o ano entra no
            # inventário assim mesmo, justamente para que a falha apareça.
            csv = None

    return Microdados(
        ano=ano,
        zip=zip_path if zip_path.exists() else None,
        parcial=parcial if parcial.exists() and not zip_path.exists() else None,
        extraido=extraido if extraido.is_dir() else None,
        csv=csv,
        parquet=parquet if parquet.exists() else None,
    )


def formatar(itens: list[Microdados], *, paths: Paths | None = None) -> str:
    """Monta a tabela que o ``censo listar`` imprime."""
    paths = paths or get_paths()
    if not itens:
        return (
            f"Nenhum microdado em {paths.data}.\n"
            "Rode: censo obter <ano>   (ou: make dados ANO=2023)"
        )

    cabecalho = ("ANO", "ZIP", "EXTRAÍDO", "CSV DE ESCOLAS", "PARQUET")
    linhas = [cabecalho, *(_linha(item) for item in itens)]
    larguras = [max(len(linha[i]) for linha in linhas) for i in range(len(cabecalho))]
    def formatar_linha(linha: tuple[str, ...]) -> str:
        campos = zip(linha, larguras, strict=True)
        return "  ".join(campo.ljust(largura) for campo, largura in campos).rstrip()

    tabela = "\n".join(formatar_linha(linha) for linha in linhas)

    baixados = [i for i in itens if i.zip]
    total = sum(_tamanho(i.zip) for i in baixados)
    rodape = (
        f"{len(baixados)} ano(s) baixado(s), {sum(1 for i in itens if i.completo)} extraído(s), "
        f"{sum(1 for i in itens if i.parquet)} em Parquet — {_humano(total)} em {paths.raw}"
    )
    return f"{tabela}\n\n{rodape}"


def _linha(item: Microdados) -> tuple[str, str, str, str, str]:
    if item.zip:
        zip_col = _humano(_tamanho(item.zip))
    elif item.parcial:
        zip_col = f"parcial ({_humano(_tamanho(item.parcial))})"
    else:
        zip_col = "—"

    if item.csv:
        csv_col = f"{item.csv.name} ({_humano(_tamanho(item.csv))})"
    elif item.extraido:
        csv_col = "não encontrado"
    else:
        csv_col = "—"

    return (
        str(item.ano),
        zip_col,
        "sim" if item.extraido else "—",
        csv_col,
        _humano(_tamanho(item.parquet)) if item.parquet else "—",
    )


def _tamanho(caminho: Path) -> int:
    return caminho.stat().st_size


def _humano(bytes_: int) -> str:
    """Tamanho em binário (KiB/MiB/GiB), a unidade que o ``ls -lh`` mostra."""
    valor = float(bytes_)
    for unidade in ("B", "KiB", "MiB"):
        if valor < 1024:
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} GiB"
