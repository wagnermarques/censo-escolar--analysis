PY      ?= python3
VENV    ?= .venv
BIN     := $(VENV)/bin
ANO     ?= 2023

.PHONY: ajuda venv instalar dados parquet sync check-sync nb org kernel lab test lint limpar

ajuda:
	@echo "Alvos disponíveis:"
	@echo "  make venv          cria o ambiente virtual em $(VENV)"
	@echo "  make instalar      instala o pacote em modo editável + extras"
	@echo "  make kernel        registra o kernel Jupyter 'censo-escolar'"
	@echo "  make dados ANO=2023    baixa e extrai os microdados do ano"
	@echo "  make parquet ANO=2023  converte o CSV de escolas para Parquet"
	@echo "  make sync          sincroniza notebooks/*.org <-> *.ipynb (pelo mtime)"
	@echo "  make check-sync    falha se algum par estiver fora de sincronia"
	@echo "  make nb            força .org -> .ipynb em todos os documentos"
	@echo "  make org           força .ipynb -> .org em todos os documentos"
	@echo "  make lab           abre o JupyterLab"
	@echo "  make test / lint   pytest / ruff"

venv:
	$(PY) -m venv $(VENV)

instalar: venv
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[notebook,dev]"

kernel:
	$(BIN)/python -m ipykernel install --user \
		--name censo-escolar --display-name "Python (censo-escolar)"

dados:
	$(BIN)/censo obter $(ANO)

parquet:
	$(BIN)/censo parquet $(ANO)

sync:
	$(BIN)/python -m censo_escolar.orgnb sync notebooks

check-sync:
	$(BIN)/python -m censo_escolar.orgnb sync notebooks --check

nb:
	@for f in notebooks/*.org; do $(BIN)/python -m censo_escolar.orgnb org2nb "$$f"; done

org:
	@for f in notebooks/*.ipynb; do $(BIN)/python -m censo_escolar.orgnb nb2org "$$f"; done

lab:
	$(BIN)/jupyter lab notebooks

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check src tests

limpar:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ src/*.egg-info
