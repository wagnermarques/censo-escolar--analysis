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
CENSO   := $(BIN)/censo$(EXE)

.PHONY: ajuda help venv instalar certificados dados list parquet dicionario lab test lint limpar

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
	@echo "  make certificados  monta o bundle de CAs do INEP (só se o TLS falhar)"
	@echo "  make dados ANO=2023    baixa e extrai os microdados do ano"
	@echo "  make dados list        lista o que já está no disco (= make list)"
	@echo "  make parquet ANO=2023  converte o CSV de escolas para Parquet"
	@echo "  make dicionario    descreve as colunas comuns a todos os anos baixados"
	@echo "  make lab           abre o JupyterLab"
	@echo "  make test / lint   pytest / ruff"
	@echo "  make limpar        remove caches (.pytest_cache, __pycache__, ...)"
	@echo "  make help / ajuda  esta lista"
	@echo ""
	@echo "Python do venv detectado: $(PYTHON)"
	@echo ""
	@echo "Sem make (Windows sem WSL/Git Bash)? '$(PY) -m venv .venv' + "
	@echo "'.venv/bin/pip install -e \".[notebook,dev]\"' (.venv\\Scripts\\pip no"
	@echo "cmd.exe/PowerShell) substituem venv+instalar; depois disso, use o"
	@echo "'censo' que ficou dentro do venv para os demais alvos — é o mesmo"
	@echo "$(CENSO) que este Makefile chama por baixo."

venv:
	$(PY) -m venv $(VENV)

instalar: venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[notebook,dev]"

certificados:
	$(CENSO) certificados --forcar

# `make dados list`: `list` aqui é um modificador, não um alvo de verdade — mas
# o make trata cada palavra da linha de comando como um alvo, e não há como um
# alvo receber argumento. Então os dois se combinam: `dados` não baixa nada
# quando `list` também foi pedido, e é `list` quem imprime o inventário. Quem
# preferir a forma curta chama `make list` direto.
dados:
ifeq (,$(filter list,$(MAKECMDGOALS)))
	$(CENSO) obter $(ANO)
else
	@:
endif

list:
	$(CENSO) listar

parquet:
	$(CENSO) parquet $(ANO)

# Sem ANO: o dicionário só faz sentido sobre o conjunto de anos, não sobre um.
dicionario:
	$(CENSO) dicionario

lab:
	$(CENSO) lab

test:
	$(CENSO) test

lint:
	$(CENSO) lint

limpar:
	$(CENSO) limpar
