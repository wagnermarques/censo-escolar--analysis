"""Interface de linha de comando do projeto (``censo ...``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from censo_escolar import loading, orgnb
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

    p_parquet = sub.add_parser("parquet", help="converte o CSV de escolas para Parquet")
    p_parquet.add_argument("ano", type=int)
    p_parquet.add_argument("--forcar", action="store_true")

    p_colunas = sub.add_parser("colunas", help="lista as colunas do arquivo de escolas")
    p_colunas.add_argument("ano", type=int)
    p_colunas.add_argument("--filtro", help="mostra só as colunas que contêm este texto")

    sub.add_parser("caminhos", help="mostra os diretórios resolvidos do projeto")

    p_certs = sub.add_parser(
        "certificados", help="monta o bundle de CAs que valida o servidor do INEP"
    )
    p_certs.add_argument("--forcar", action="store_true")

    p_sync = sub.add_parser("sync", help="sincroniza .org <-> .ipynb")
    p_sync.add_argument("diretorio", type=Path, nargs="?")
    p_sync.add_argument("--check", action="store_true")

    args = parser.parse_args(argv)

    try:
        return _executar(args)
    except FileNotFoundError as erro:
        # `AnoIndisponivel`, ZIP não baixado, microdados não extraídos: todos
        # já trazem a instrução do que fazer a seguir. O traceback só esconderia
        # o recado. Erros que *não* previmos continuam subindo inteiros.
        print(f"censo: {erro}", file=sys.stderr)
        return 1


def _executar(args: argparse.Namespace) -> int:
    match args.comando:
        case "baixar":
            print(baixar_ano(args.ano, url=args.url, forcar=args.forcar))
        case "extrair":
            print(extrair_ano(args.ano, forcar=args.forcar))
        case "obter":
            print(obter_ano(args.ano, url=args.url))
        case "parquet":
            print(loading.converter_para_parquet(args.ano, forcar=args.forcar))
        case "colunas":
            colunas = loading.colunas_disponiveis(args.ano)
            if args.filtro:
                alvo = args.filtro.upper()
                colunas = [c for c in colunas if alvo in c.upper()]
            print("\n".join(colunas))
            print(f"\n({len(colunas)} colunas)")
        case "certificados":
            print(preparar_ca_bundle(forcar=args.forcar))
        case "caminhos":
            paths = get_paths()
            for campo, valor in vars(paths).items():
                print(f"{campo:12} {valor}")
        case "sync":
            diretorio = args.diretorio or get_paths().notebooks
            pendentes = orgnb.sincronizar(diretorio, checar=args.check)
            if args.check and pendentes:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
