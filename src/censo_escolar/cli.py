"""Interface de linha de comando do projeto (``censo ...``)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from censo_escolar import amostra, esquema, inventario, loading
from censo_escolar.config import get_paths
from censo_escolar.download import baixar_ano, extrair_ano, obter_ano, preparar_ca_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="censo", description="Microdados do Censo Escolar (INEP)")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_baixar = sub.add_parser("baixar", help="baixa o ZIP de microdados de um ano")
    p_baixar.add_argument("ano", type=int)
    p_baixar.add_argument("--url", help="sobrepõe a URL (use {ano} como marcador)")
    p_baixar.add_argument("--forcar", action="store_true")

    p_extrair = sub.add_parser("extrair", help="extrai um ZIP já baixado")
    p_extrair.add_argument("ano", type=int)
    p_extrair.add_argument("--forcar", action="store_true")

    p_obter = sub.add_parser("obter", help="baixa e extrai")
    p_obter.add_argument("ano", type=int)
    p_obter.add_argument("--url")

    sub.add_parser("listar", help="lista os microdados que já estão no disco")

    p_parquet = sub.add_parser("parquet", help="converte o CSV de escolas para Parquet")
    p_parquet.add_argument("ano", type=int)
    p_parquet.add_argument("--forcar", action="store_true")

    p_amostra = sub.add_parser(
        "amostra",
        help="recorta as primeiras linhas num arquivo que o Calc/Excel abre inteiro",
    )
    p_amostra.add_argument("ano", type=int, nargs="?")
    p_amostra.add_argument(
        "--arquivo", type=Path, help="recorta este CSV em vez do de escolas do ano"
    )
    p_amostra.add_argument("--linhas", type=int, default=amostra.LINHAS_PADRAO)
    p_amostra.add_argument("--colunas", help="lista separada por vírgula; padrão: todas")
    p_amostra.add_argument(
        "--onde", action="append", metavar="COLUNA=VALOR", help="igualdade exata; repetível"
    )
    p_amostra.add_argument(
        "--contem", action="append", metavar="COLUNA=TEXTO", help="busca no meio do texto"
    )
    p_amostra.add_argument("--saida", type=Path, help=".xlsx (padrão) ou .csv")
    p_amostra.add_argument(
        "--abrir", action="store_true", help="abre o arquivo no programa padrão do sistema"
    )

    p_colunas = sub.add_parser("colunas", help="lista as colunas do arquivo de escolas")
    p_colunas.add_argument("ano", type=int)
    p_colunas.add_argument("--filtro", help="mostra só as colunas que contêm este texto")

    p_comuns = sub.add_parser("comuns", help="colunas presentes em todos os anos informados")
    p_comuns.add_argument("anos", type=int, nargs="*", help="padrão: todos os anos extraídos")

    p_dic = sub.add_parser(
        "dicionario", help="monta o dicionário de dados das colunas comuns entre anos"
    )
    p_dic.add_argument("anos", type=int, nargs="*", help="padrão: todos os anos extraídos")
    p_dic.add_argument(
        "--linhas",
        type=int,
        help="perfila só as N primeiras linhas de cada ano (ensaio rápido, tipo não confiável)",
    )
    p_dic.add_argument("--todas", action="store_true", help="inclui também as colunas não comuns")
    p_dic.add_argument("--saida", type=Path, help="CSV de destino")

    sub.add_parser("caminhos", help="mostra os diretórios resolvidos do projeto")

    p_certs = sub.add_parser(
        "certificados", help="monta o bundle de CAs que valida o servidor do INEP"
    )
    p_certs.add_argument("--forcar", action="store_true")

    sub.add_parser(
        "limpar",
        help="remove caches de build/teste (__pycache__, .pytest_cache, .ruff_cache, *.egg-info)",
    )

    # `lab`, `test` e `lint` são a mesma ideia que `baixar`/`parquet`: embrulhar
    # `sys.executable -m <ferramenta>` em vez de depender de um executável no
    # PATH. Isto é o que dá paridade com o Makefile sem precisar de shell
    # nenhum — o mesmo comando `censo <alvo>` funciona em Linux, macOS e
    # Windows, com ou sem `make` instalado.
    sub.add_parser("lab", help="abre o JupyterLab em notebooks/")

    p_test = sub.add_parser("test", help="roda a suíte de testes (pytest)")
    p_test.add_argument(
        "pytest_args", nargs=argparse.REMAINDER, help="argumentos extras repassados ao pytest"
    )

    p_lint = sub.add_parser("lint", help="roda o linter (ruff check src tests)")
    p_lint.add_argument(
        "ruff_args", nargs=argparse.REMAINDER, help="argumentos extras repassados ao ruff"
    )

    args = parser.parse_args(argv)

    try:
        return _executar(args)
    except (FileNotFoundError, KeyError, ValueError) as erro:
        # `AnoIndisponivel`, ZIP não baixado, microdados não extraídos, coluna
        # que não existe, `--onde` mal escrito: todos já trazem a instrução do
        # que fazer a seguir. O traceback só esconderia o recado. Erros que
        # *não* previmos continuam subindo inteiros.
        print(f"censo: {erro.args[0] if erro.args else erro}", file=sys.stderr)
        return 1


def _executar(args: argparse.Namespace) -> int:
    match args.comando:
        case "baixar":
            print(baixar_ano(args.ano, url=args.url, forcar=args.forcar))
        case "extrair":
            print(extrair_ano(args.ano, forcar=args.forcar))
        case "obter":
            print(obter_ano(args.ano, url=args.url))
        case "listar":
            print(inventario.formatar(inventario.inventariar()))
        case "parquet":
            print(loading.converter_para_parquet(args.ano, forcar=args.forcar))
        case "amostra":
            return _amostra(args)
        case "colunas":
            colunas = loading.colunas_disponiveis(args.ano)
            if args.filtro:
                alvo = args.filtro.upper()
                colunas = [c for c in colunas if alvo in c.upper()]
            print("\n".join(colunas))
            print(f"\n({len(colunas)} colunas)")
        case "comuns":
            anos = _anos_ou_todos(args.anos)
            comuns = esquema.colunas_comuns(anos)
            print("\n".join(comuns))
            print(f"\n({len(comuns)} colunas comuns a {_faixa(anos)})")
        case "dicionario":
            anos = _anos_ou_todos(args.anos)
            escopo = (
                f"as {args.linhas} primeiras linhas — tipo não confiável"
                if args.linhas
                else "varredura completa dos CSVs"
            )
            print(f"Perfilando {_faixa(anos)}… ({escopo})", file=sys.stderr)
            dic = esquema.dicionario_de_dados(
                anos, apenas_comuns=not args.todas, linhas=args.linhas
            )
            destino = esquema.salvar_dicionario(dic, args.saida)
            instaveis = int((~dic["tipo_estavel"]).sum())
            print(f"{len(dic)} variáveis descritas ({instaveis} com tipo instável entre anos)")
            print(destino)
        case "certificados":
            print(preparar_ca_bundle(forcar=args.forcar))
        case "caminhos":
            paths = get_paths()
            for campo, valor in vars(paths).items():
                print(f"{campo:12} {valor}")
        case "limpar":
            alvos = [Path(".pytest_cache"), Path(".ruff_cache")]
            alvos += list(Path(".").rglob("__pycache__"))
            alvos += list(Path("src").glob("*.egg-info"))
            for alvo in alvos:
                shutil.rmtree(alvo, ignore_errors=True)
            print(f"{len(alvos)} diretório(s) removido(s)")
        case "lab":
            return _rodar([sys.executable, "-m", "jupyter", "lab", str(get_paths().notebooks)])
        case "test":
            return _rodar([sys.executable, "-m", "pytest", *args.pytest_args])
        case "lint":
            return _rodar([sys.executable, "-m", "ruff", "check", "src", "tests", *args.ruff_args])
    return 0


def _amostra(args: argparse.Namespace) -> int:
    """Recorta e grava; o relatório vai para stderr, o caminho para stdout.

    A separação existe para o caminho poder ser encanado (``$(censo amostra
    2023 --saida -)`` não faz sentido, mas ``xdg-open "$(censo amostra 2023)"``
    faz) sem que o resumo atrapalhe.
    """
    try:
        recorte, origem, lidas = amostra.amostrar(
            args.ano,
            arquivo=args.arquivo,
            linhas=args.linhas,
            colunas=args.colunas.split(",") if args.colunas else None,
            onde=amostra.pares_de_filtro(args.onde, "onde"),
            contem=amostra.pares_de_filtro(args.contem, "contem"),
        )
    except amostra.SemLinhas as erro:
        print(f"censo: {erro}", file=sys.stderr)
        return 1

    destino = args.saida or amostra.caminho_amostra(origem)
    destino = amostra.salvar(recorte, destino)
    print(
        f"{len(recorte)} linha(s) x {len(recorte.columns)} coluna(s) "
        f"de {origem.name} ({lidas} linha(s) varrida(s))",
        file=sys.stderr,
    )
    print(destino)
    if args.abrir:
        amostra.abrir_no_sistema(destino)
    return 0


def _anos_ou_todos(anos: list[int]) -> list[int]:
    """Anos pedidos na linha de comando, ou todos os extraídos se ninguém pediu."""
    if anos:
        return sorted(anos)
    encontrados = esquema.anos_disponiveis()
    if not encontrados:
        raise FileNotFoundError(
            "Nenhum ano extraído em data/interim/.\nRode: censo obter <ano>"
        )
    return encontrados


def _faixa(anos: list[int]) -> str:
    """`2019-2025` quando a lista é contígua; a lista inteira quando não é."""
    if len(anos) > 1 and anos == list(range(anos[0], anos[-1] + 1)):
        return f"{anos[0]}-{anos[-1]}"
    return ", ".join(str(a) for a in anos)


def _rodar(comando: list[str]) -> int:
    """Executa uma ferramenta externa herdando stdio; devolve o código de saída."""
    return subprocess.run(comando, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
