VENV    ?= .venv
ANO     ?= 2023

# --------------------------------------------------------------------------
# Onde este venv guarda os executáveis
# --------------------------------------------------------------------------
# `bin/` no POSIX, `Scripts/` (com .exe) no Windows. Perguntamos ao disco, não
# ao sistema operacional: a pergunta real é sobre *este* venv, não sobre quem
# está rodando o make. A diferença aparece nos casos mistos — o WSL enxergando
# um venv criado pelo Python do Windows tem $(OS) vazio, e a detecção por SO
# escolheria `bin/` e quebraria.
ifneq ($(wildcard $(VENV)/Scripts/python.exe),)
  BIN := $(VENV)/Scripts
  EXE := .exe
else ifneq ($(wildcard $(VENV)/bin/python),)
  BIN := $(VENV)/bin
  EXE :=
else ifeq ($(OS),Windows_NT)
  # Ainda não há venv (o caso do `make venv`): sem disco para consultar, o
  # sistema operacional é o melhor palpite disponível.
  BIN := $(VENV)/Scripts
  EXE := .exe
else
  BIN := $(VENV)/bin
  EXE :=
endif

# O Python do sistema, usado só para criar o venv. Aqui a pergunta é mesmo
# sobre o sistema operacional: o instalador do Windows entrega o lançador `py`.
ifeq ($(OS),Windows_NT)
  PY ?= py
else
  PY ?= python3
endif

PYTHON  := $(BIN)/python$(EXE)
PIP     := $(BIN)/pip$(EXE)
JUPYTER := $(BIN)/jupyter$(EXE)
PYTEST  := $(BIN)/pytest$(EXE)
RUFF    := $(BIN)/ruff$(EXE)
CENSO   := $(BIN)/censo$(EXE)
ORGNB   := $(PYTHON) -m censo_escolar.orgnb

.PHONY: ajuda help venv instalar certificados dados parquet sync check-sync nb org kernel lab test lint limpar

# `make` sem alvo lista a ajuda, não roda venv — o primeiro alvo do arquivo
# seria o padrão por acidente, e ninguém quer criar um venv sem pedir.
.DEFAULT_GOAL := help

# `help` é o nome que a mão digita por hábito (make help é quase universal);
# `ajuda` é o nome que combina com o resto do Makefile, em português.
help: ajuda

ajuda:
	@echo "Alvos disponíveis:"
	@echo "  make venv          cria o ambiente virtual em $(VENV)"
	@echo "  make instalar      instala o pacote em modo editável + extras"
	@echo "  make kernel        registra o kernel Jupyter 'censo-escolar'"
	@echo "  make certificados  monta o bundle de CAs do INEP (só se o TLS falhar)"
	@echo "  make dados ANO=2023    baixa e extrai os microdados do ano"
	@echo "  make parquet ANO=2023  converte o CSV de escolas para Parquet"
	@echo "  make sync          sincroniza notebooks/*.org <-> *.ipynb (pelo mtime)"
	@echo "  make check-sync    falha se algum par estiver fora de sincronia"
	@echo "  make nb            força .org -> .ipynb em todos os documentos"
	@echo "  make org           força .ipynb -> .org em todos os documentos"
	@echo "  make lab           abre o JupyterLab"
	@echo "  make test / lint   pytest / ruff"
	@echo "  make limpar        remove caches (.pytest_cache, __pycache__, ...)"
	@echo "  make help / ajuda  esta lista"
	@echo ""
	@echo "Python do venv detectado: $(PYTHON)"

venv:
	$(PY) -m venv $(VENV)

instalar: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[notebook,dev]"

kernel:
	$(PYTHON) -m ipykernel install --user \
		--name censo-escolar --display-name "Python (censo-escolar)"

certificados:
	$(CENSO) certificados --forcar

dados:
	$(CENSO) obter $(ANO)

parquet:
	$(CENSO) parquet $(ANO)

sync:
	$(ORGNB) sync notebooks

check-sync:
	$(ORGNB) sync notebooks --check

# O laço de shell saiu daqui: `orgnb` aceita um diretório e faz o glob em
# Python, que roda igual no cmd.exe, no bash e no WSL.
nb:
	$(ORGNB) org2nb notebooks

org:
	$(ORGNB) nb2org notebooks

lab:
	$(JUPYTER) lab notebooks

test:
	$(PYTEST)

lint:
	$(RUFF) check src tests

# `rm -rf` e o glob `**/` são do shell POSIX; em Python isto vale nos dois
# mundos e ainda funciona quando o venv nem existe.
limpar:
	$(PY) -c "import pathlib, shutil; \
		alvos = [pathlib.Path('.pytest_cache'), pathlib.Path('.ruff_cache')] \
		+ list(pathlib.Path('.').rglob('__pycache__')) \
		+ list(pathlib.Path('src').glob('*.egg-info')); \
		[shutil.rmtree(a, ignore_errors=True) for a in alvos]"
