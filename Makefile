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

.PHONY: ajuda help venv instalar certificados dados list parquet amostra dicionario map site servir ibge-malhas ibge-malha-municipal lab test lint limpar todas abrir

# `make` sem alvo lista a ajuda, não roda venv — o primeiro alvo do arquivo
# seria o padrão por acidente, e ninguém quer criar um venv sem pedir.
.DEFAULT_GOAL := help

# Os alvos que têm ajuda detalhada. A lista serve duas vezes: para achar o
# assunto de `make help <alvo>` e para desligar as receitas de verdade
# enquanto a ajuda está sendo pedida.
COMANDOS := venv instalar certificados dados list parquet amostra dicionario map site servir ibge-malhas ibge-malha-municipal lab test lint limpar

# `make help dicionario`: mesmo mecanismo de `make dados list` — o make trata
# cada palavra da linha de comando como um alvo, e não há como um alvo receber
# argumento. Então a palavra ao lado de `help` é lida aqui como *assunto* da
# ajuda, e o alvo correspondente vira receita vazia lá embaixo. Sem isso,
# `make help dicionario` imprimiria a ajuda e em seguida montaria o dicionário
# de verdade — meia hora de varredura que ninguém pediu.
PEDIU_AJUDA := $(filter help ajuda,$(MAKECMDGOALS))
ASSUNTOS    := $(filter-out help ajuda,$(MAKECMDGOALS))
CONHECIDOS  := $(filter $(COMANDOS),$(ASSUNTOS))

# --------------------------------------------------------------------------
# Modificadores: as palavras que acompanham um alvo
# --------------------------------------------------------------------------
# A mesma ideia do `make dados list`, generalizada: o make não sabe passar
# argumento para um alvo, então as outras palavras da linha são lidas aqui e o
# alvo de verdade decide o que fazer com elas. `todas` liga o --todas do
# dicionário; um ano solto (`make dados 2023`, `make dicionario 2019 2023`) diz
# de que ano se está falando.
ANOS_NA_LINHA  := $(filter 19% 20%,$(MAKECMDGOALS))
TODAS_NA_LINHA := $(filter todas,$(MAKECMDGOALS))
ABRIR_NA_LINHA := $(filter abrir,$(MAKECMDGOALS))

# `make map QT_MAT_BAS "https://…"`: os dois argumentos do mapa também são
# palavras soltas, reconhecidas pelo que são. A variável, pelo prefixo
# padronizado do INEP; a URL, por começar com http.
#
# A URL sobrevive como palavra da linha de comando por um detalhe do make: uma
# palavra com `=` vira atribuição de variável, *exceto* se houver `:` antes do
# primeiro `=` — e toda URL tem `://`. Já as aspas são exigência do shell, não
# do make: sem elas o `&` da URL manda o comando para segundo plano.
VARIAVEL_INEP  := $(filter QT_% IN_% TP_%,$(MAKECMDGOALS))
URL_MALHA      := $(filter http%,$(MAKECMDGOALS))
MODIFICADORES  := list todas abrir $(ANOS_NA_LINHA) $(VARIAVEL_INEP) $(URL_MALHA)

DESCONHECIDOS := $(filter-out $(COMANDOS) $(MODIFICADORES),$(ASSUNTOS))

# `ANO=2023` na linha de comando ganha de qualquer atribuição do makefile, então
# quem escreveu as duas formas continua mandando na explícita.
ifneq (,$(ANOS_NA_LINHA))
ANO := $(lastword $(ANOS_NA_LINHA))
endif

# Opções do `censo dicionario`. `--todas` não pode ser digitado direto no make
# (ele lê qualquer `--coisa` como opção *dele*), daí a palavra sem traços; as
# demais são variáveis porque carregam valor.
ANOS_DIC   := $(strip $(ANOS) $(ANOS_NA_LINHA))
OPCOES_DIC := $(if $(TODAS_NA_LINHA)$(TODAS),--todas)
OPCOES_DIC += $(if $(LINHAS),--linhas $(LINHAS))
OPCOES_DIC += $(if $(SAIDA),--saida $(SAIDA))

# Opções da amostra. Aspas duplas porque CONTEM= costuma levar espaço ("escola
# municipal") — e duplas, não simples, porque o cmd.exe entende as duplas.
OPCOES_AM := $(if $(LINHAS),--linhas $(LINHAS))
OPCOES_AM += $(if $(COLUNAS),--colunas "$(COLUNAS)")
OPCOES_AM += $(if $(ONDE),--onde "$(ONDE)")
OPCOES_AM += $(if $(CONTEM),--contem "$(CONTEM)")
OPCOES_AM += $(if $(SAIDA),--saida "$(SAIDA)")
OPCOES_AM += $(if $(ABRIR_NA_LINHA)$(ABRIR),--abrir)

# Opções do mapa. TITULO leva espaço, daí as aspas duplas (que o cmd.exe
# também entende).
OPCOES_MAP := $(if $(CATEGORIA),--categoria $(CATEGORIA))
OPCOES_MAP += $(if $(TITULO),--titulo "$(TITULO)")

# As checagens abaixo param o make *antes* de qualquer receita. É o que separa
# `make dicionario fubá` de meia hora de varredura seguida de "Sem regra para
# processar o alvo 'fubá'" — o alvo pedido roda inteiro antes de o make chegar
# na palavra que não entende. Com `help` na linha nada disso vale: lá toda
# palavra é assunto, e quem responde é a ajuda.
ifeq (,$(PEDIU_AJUDA))
ifneq (,$(DESCONHECIDOS))
$(error não conheço '$(DESCONHECIDOS)'. `make ajuda` lista os alvos; `make help <alvo>` detalha um deles)
endif
ifneq (,$(TODAS_NA_LINHA))
ifeq (,$(filter dicionario,$(MAKECMDGOALS)))
$(error `todas` acompanha um alvo, não é um alvo: rode `make dicionario todas`)
endif
endif
ifneq (,$(ABRIR_NA_LINHA))
ifeq (,$(filter amostra,$(MAKECMDGOALS)))
$(error `abrir` acompanha um alvo, não é um alvo: rode `make amostra abrir`)
endif
endif
ifneq (,$(filter map,$(MAKECMDGOALS)))
ifeq (,$(VARIAVEL_INEP))
$(error `make map` precisa da variável do INEP: make map QT_MAT_BAS "<url da malha>")
endif
ifeq (,$(URL_MALHA))
$(error `make map` precisa da URL da malha do IBGE, entre aspas: make map $(VARIAVEL_INEP) "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?intrarregiao=UF&qualidade=minima")
endif
endif
ifneq (,$(VARIAVEL_INEP))
ifeq (,$(filter map,$(MAKECMDGOALS)))
$(error a variável $(VARIAVEL_INEP) acompanha `make map`, não é um alvo)
endif
endif
ifneq (,$(ANOS_NA_LINHA))
ifeq (,$(filter dados parquet amostra dicionario map,$(MAKECMDGOALS)))
$(error o ano acompanha um alvo, não é um alvo: rode `make dados $(lastword $(ANOS_NA_LINHA))`)
endif
endif
endif

# --------------------------------------------------------------------------
# Os textos de ajuda
# --------------------------------------------------------------------------
# Cada bloco é uma variável de várias linhas impressa com $(info ...), e não
# com @echo: $(info) preserva as quebras de linha sem uma chamada de shell por
# linha, e funciona igual no cmd.exe, onde não há `echo` do sh para chamar.

define AJUDA_GERAL
Alvos disponíveis:
  make venv                cria o ambiente virtual em $(VENV)
  make instalar            instala o pacote em modo editável + extras
  make certificados        monta o bundle de CAs do INEP (só se o TLS falhar)
  make dados 2023          baixa e extrai os microdados do ano (= ANO=2023)
  make dados list          lista o que já está no disco (= make list)
  make parquet 2023        converte o CSV de escolas para Parquet
  make amostra 2023        recorta as 100 primeiras linhas num .xlsx (abre no Calc)
  make dicionario          descreve as colunas comuns a todos os anos baixados
  make dicionario todas    o dicionário com as colunas não comuns também
  make map QT_MAT_BAS "<url do IBGE>" 2023   assa um mapa do site
  make site                reassa todos os mapas de site/consultas.txt
  make servir              serve site/ em http://localhost:8000
  make ibge-malhas         pré-baixa as malhas do IBGE para o cache
  make lab                 abre o JupyterLab
  make test / lint         pytest / ruff
  make limpar              remove caches (.pytest_cache, __pycache__, ...)
  make help / ajuda        esta lista
  make help <alvo>         ajuda detalhada de um alvo (ex.: make help dicionario)

Python do venv detectado: $(PYTHON)

Sem make (Windows sem WSL/Git Bash)? '$(PY) -m venv .venv' +
'.venv/bin/pip install -e ".[notebook,dev]"' (.venv\Scripts\pip no
cmd.exe/PowerShell) substituem venv+instalar; depois disso, use o
'censo' que ficou dentro do venv para os demais alvos — é o mesmo
$(CENSO) que este Makefile chama por baixo.
endef

define AJUDA_venv
make venv

  Cria o ambiente virtual em $(VENV), usando o Python do sistema ($(PY)).
  Só isso: não instala nada dentro dele. Na prática você quer `make instalar`,
  que depende deste alvo e já o executa.

  Variáveis: VENV=$(VENV) (destino), PY=$(PY) (Python que cria o venv).
    make venv VENV=.venv313 PY=python3.13

  Chama: $(PY) -m venv $(VENV)
endef

define AJUDA_instalar
make instalar

  Instala o pacote em modo editável (-e) com os extras [notebook,dev]:
  JupyterLab e ipykernel, pytest e ruff. Depende de `venv`, então numa máquina
  limpa este é o primeiro e único comando de instalação.

  Modo editável quer dizer que o código em src/ é o que roda: editar um .py já
  vale para o próximo `censo ...`, sem reinstalar nada.

  Depois dele existe o executável $(CENSO), que é quem faz o trabalho de
  todos os outros alvos deste Makefile.

  Chama: $(PYTHON) -m pip install -e ".[notebook,dev]"
endef

define AJUDA_certificados
make certificados

  Monta o bundle de CAs que valida o servidor do INEP e grava em certs/.

  Rode só se um download falhar com erro de TLS/certificado. No caso normal o
  bundle de CAs do sistema já dá conta e este alvo é desnecessário.

  Chama: $(CENSO) certificados --forcar
endef

define AJUDA_dados
make dados ANO=2023

  Baixa o ZIP de microdados do ano no INEP e extrai em data/interim/. Sem
  ANO=, usa o padrão do Makefile (hoje $(ANO)). O que já está no disco não é
  baixado de novo.

  make dados 2023    o mesmo que ANO=2023 — um ano solto na linha vale por ele
  make dados list    não baixa nada: lista o inventário (o mesmo que make list)

  O `list` e o ano aqui são modificadores, não alvos de verdade — são a forma
  de passar argumento para um alvo, que o make não tem.

  Chama: $(CENSO) obter $(ANO)
endef

define AJUDA_list
make list

  Inventário do que já está em data/: quais anos foram baixados, quais foram
  extraídos, quais já viraram Parquet. É a resposta a "o que eu já tenho aqui?"
  sem abrir três diretórios na mão.

  Forma longa equivalente: make dados list

  Chama: $(CENSO) listar
endef

define AJUDA_parquet
make parquet ANO=2023

  Converte o CSV de escolas do ano para Parquet, em data/processed/. O ano vem
  de ANO=2023 ou solto na linha (make parquet 2023); sem nenhum dos dois, vale
  o padrão do Makefile (hoje $(ANO)).

  É opcional, mas recomendado: as leituras seguintes ficam ~10x mais rápidas e
  passam a carregar só as colunas pedidas, em vez do CSV inteiro.

  Requer o ano já extraído — rode `make dados ANO=...` antes.

  Chama: $(CENSO) parquet $(ANO)
endef

define AJUDA_amostra
make amostra 2023

  Recorta as primeiras linhas do CSV de escolas do ano num .xlsx pequeno,
  gravado em data/processed/, e imprime o caminho. É a forma de *ver* os
  microdados numa máquina que não aguenta abrir o arquivo inteiro: o Calc
  carrega a planilha toda na memória antes de desenhar a primeira célula, e
  nem ele nem o Excel sabem importar "só as N primeiras linhas".

  O .xlsx sai pronto para leitura: cabeçalho em negrito e congelado, AutoFiltro
  ligado (o menuzinho em cada coluna) e larguras ajustadas. Abre com dois
  cliques, sem diálogo de importação — sem escolher encoding nem separador, que
  é onde o CSV do INEP costuma ser lido errado.

    make amostra 2023 LINHAS=500          quantas linhas trazer (padrão: 100)
    make amostra 2023 COLUNAS=CO_ENTIDADE,NO_ENTIDADE,QT_MAT_BAS
    make amostra 2023 ONDE=SG_UF=MG       só as linhas com esse valor exato
    make amostra 2023 CONTEM=NO_ENTIDADE=quilombola    busca no meio do texto
    make amostra 2023 SAIDA=recorte.csv   .csv em vez de .xlsx (UTF-8 com BOM)
    make amostra 2023 abrir               abre no programa padrão do sistema

  ONDE e CONTEM são a busca que a máquina não aguenta fazer com o arquivo
  aberto: o CSV é lido em blocos e a leitura para assim que as linhas pedidas
  aparecem, então a memória usada não depende do tamanho do arquivo.

  Para recortar outro CSV que não o de escolas (as tabelas de Matrícula, Turma
  ou Docente de 2025, por exemplo), ou para repetir --onde/--contem, chame o
  CLI direto:
    $(CENSO) amostra --arquivo data/interim/2025/Tabela_Matricula_2025_V2.csv
    $(CENSO) amostra 2023 --onde SG_UF=MG --onde TP_DEPENDENCIA=3

  Chama: $(strip $(CENSO) amostra $(ANO) $(OPCOES_AM))
endef

define AJUDA_map
make map <VARIAVEL> "<URL da malha do IBGE>" [anos]

  Assa um mapa do site: agrega a variável do INEP sobre as áreas da malha,
  grava o GeoJSON com o dado já dentro, escreve a página HTML e registra a
  consulta em site/consultas.txt.

  Dois argumentos e mais nada: *o quê* e *onde, em que grão*.

    make map QT_MAT_BAS "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?intrarregiao=UF&qualidade=minima" 2023
    make map IN_INTERNET "https://…/estados/31?intrarregiao=municipio&qualidade=minima" 2019 2024
    make map TP_DEPENDENCIA "https://…/estados/35?intrarregiao=microrregiao&qualidade=minima" 2023 CATEGORIA=4

  AS ASPAS SÃO OBRIGATÓRIAS. Sem elas o `&` da URL manda o comando para
  segundo plano, e nada roda. Isso é do shell, não deste Makefile.

  A URL do IBGE é a linguagem do recorte — o projeto não inventa outra:
    o caminho (/estados/35) diz QUAIS LINHAS entram;
    o intrarregiao= diz POR QUAL COLUNA agrupar (UF, mesorregiao,
      microrregiao, regiao-imediata, regiao-intermediaria, municipio);
    o properties.codarea de cada polígono casa com essa coluna, sem conversão.

  A variável decide o tipo de mapa, pela natureza que o dicionário de dados
  já classifica:
    QT_*  soma           -> coroplético do total
    IN_*  média          -> % das escolas da área
    TP_*  participação   -> % de uma categoria (exige CATEGORIA=)

  Opções: LINHAS não; ANOS soltos na linha; CATEGORIA=<código>; TITULO="...".
  Sem ano, usa o mais recente em que a variável e a coluna existem.

  Sai em: site/dados/<slug>.geojson, site/mapas/<slug>.html,
          data/processed/<slug>.csv (a tabela que gerou o mapa, conferível)

  Chama: $(strip $(CENSO) map $(VARIAVEL_INEP) "$(URL_MALHA)" $(ANOS_NA_LINHA) $(OPCOES_MAP))
endef

define AJUDA_site
make site

  Reassa TODOS os mapas a partir de site/consultas.txt e regenera o índice.
  O site é função desse arquivo: apagar um mapa é apagar uma linha; baixar um
  ano novo e rodar `make site` atualiza tudo.

  Chama: $(CENSO) site
endef

define AJUDA_servir
make servir

  Sobe um servidor local em site/ (http://localhost:8000) para conferir antes
  de publicar. Ctrl-C para parar.

  Não dá para abrir as páginas com file:// — o navegador bloqueia o fetch()
  do GeoJSON. Daí este alvo existir.

  Chama: $(CENSO) servir
endef

define AJUDA_ibge-malhas
make ibge-malhas

  Pré-baixa as malhas do IBGE mais usadas (país por UF, por região
  intermediária e por região imediata) para data/cache/malhas/, que está no
  .gitignore. É conveniência para quem vai trabalhar sem rede: o `make map`
  baixa sozinho o que faltar.

    make ibge-malhas NIVEIS=municipio        # também a municipal do Brasil
    make ibge-malha-municipal                # só a municipal (a mais pesada)

  As malhas podem ser consultadas e baixadas à mão em
  https://www.ibge.gov.br/geociencias/organizacao-do-territorio/malhas-territoriais/15774-malhas.html

  Chama: $(CENSO) malhas $(NIVEIS)
endef

define AJUDA_ibge-malha-municipal
make ibge-malha-municipal

  Só a malha municipal do Brasil (5.570 polígonos) para o cache. É a mais
  pesada — 3,6 MiB brutos, 817 KiB gzipados — por isso ficou de fora do
  `make ibge-malhas`.

  Chama: $(CENSO) malhas municipio
endef

define AJUDA_dicionario
make dicionario

  Monta o dicionário de dados das colunas comuns a todos os anos já extraídos:
  tipo, nulos, cardinalidade e exemplos de cada variável, marcando as que mudam
  de tipo de um ano para o outro. Grava um CSV em data/processed/ e imprime o
  caminho no fim.

  Sem anos: fala do *conjunto* de anos, não de um — a pergunta que ele responde
  ("dá para comparar esta coluna entre anos?") só existe no plural.

  Ele varre os CSVs inteiros, então demora. As palavras e variáveis abaixo
  recortam o trabalho:

    make dicionario todas             inclui também as colunas não comuns
    make dicionario 2019 2023         só estes anos
    make dicionario LINHAS=50000      perfila só as N primeiras linhas de cada
                                      ano — sai em segundos, mas o tipo que ele
                                      deduz não é confiável
    make dicionario SAIDA=meu.csv     escolhe o CSV de destino

  Elas se combinam: make dicionario todas 2019 2023 LINHAS=50000

  `todas` é palavra solta porque `--todas` seria lido pelo próprio make como
  opção dele. Se preferir, TODAS=1 faz o mesmo.

  Chama: $(strip $(CENSO) dicionario $(ANOS_DIC) $(OPCOES_DIC))
endef

define AJUDA_lab
make lab

  Abre o JupyterLab em notebooks/ — o Lab *do venv*, e é isso que importa: só
  ele enxerga o pacote censo_escolar. Um Lab instalado globalmente não enxerga,
  e essa é a causa mais comum de ModuleNotFoundError dentro do notebook.

  Chama: $(CENSO) lab
endef

define AJUDA_test
make test

  Roda a suíte de testes (pytest do venv) sobre tests/.

  Para passar argumentos ao pytest, chame o CLI direto:
    $(CENSO) test -k download -x

  Chama: $(CENSO) test
endef

define AJUDA_lint
make lint

  Roda o linter: ruff check em src e tests.

  Para passar argumentos ao ruff, chame o CLI direto:
    $(CENSO) lint --fix

  Chama: $(CENSO) lint
endef

define AJUDA_limpar
make limpar

  Remove os caches de build e de teste: .pytest_cache, .ruff_cache, todos os
  __pycache__ e src/*.egg-info.

  Não toca em data/ — os microdados baixados e os Parquet ficam onde estão.

  Chama: $(CENSO) limpar
endef

# `help` é o nome que a mão digita por hábito (make help é quase universal);
# `ajuda` é o nome que combina com o resto do Makefile, em português.
help: ajuda

# As receitas abaixo expandem para nada depois do $(info) — uma linha de receita
# vazia é trabalho nenhum para o make, e continua sem depender de shell.
# O `cd .` no fim é um comando de verdade que não faz nada — existe igual no sh
# e no cmd.exe. Está aí só para o make ver que a receita rodou alguma coisa: as
# linhas de $(info) expandem para vazio, e sem ele o make fecharia a ajuda com
# um "Nada a ser feito para 'help'".
ifeq (,$(ASSUNTOS))
ajuda:
	$(info $(AJUDA_GERAL))
	@cd .
else
ajuda:
	$(foreach alvo,$(CONHECIDOS),$(info $(AJUDA_$(alvo)))$(info ))
	$(foreach palavra,$(DESCONHECIDOS),$(info Não há alvo '$(palavra)'. `make ajuda` lista os que existem.))
	@cd .
endif

ifneq (,$(PEDIU_AJUDA))
# Com `help` na linha, todo alvo vira assunto da ajuda e nenhum executa: a
# receita é o mesmo `cd .` que não faz nada da ajuda acima. Os modificadores
# entram junto — `make help dicionario todas` é uma pergunta sobre o dicionário
# com a opção ligada, e a linha "Chama:" da ajuda mostra o comando que sairia.
$(COMANDOS) todas abrir $(ANOS_NA_LINHA) $(VARIAVEL_INEP):
	@cd .

# A URL não entra numa linha de regra: `https://x` faria o make ler `https`
# como alvo e `//x` como pré-requisito. O curinga resolve sem citá-la, e só
# vale quando `map` está na linha — a validação lá de cima já barrou o que
# não for variável, ano, URL ou alvo conhecido.
ifneq (,$(filter map,$(MAKECMDGOALS)))
%:
	@cd .
endif
# E as palavras que não são alvo nenhum precisam existir como alvo mesmo assim,
# senão `make help fubá` morre em "No rule to make target" antes de imprimir a
# mensagem da ajuda. (Alvos em .PHONY não pegam regras implícitas, por isso a
# regra de cima continua necessária.)
%:
	@cd .
else

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
ifeq (,$(filter list,$(MAKECMDGOALS)))
dados:
	$(CENSO) obter $(ANO)
else
# O trabalho aqui é todo do alvo `list`; `dados` só precisa não fazer nada sem
# o make reclamar "Nada a ser feito". Daí o `cd .`, que existe no sh e no
# cmd.exe — onde o make do Windows cai quando não acha um sh no PATH, e onde
# `@:`, builtin do sh, não existiria.
dados:
	@cd .
endif

list:
	$(CENSO) listar

# `todas` e os anos soltos são modificadores, não alvos — mas o make executa
# toda palavra da linha, então cada um precisa existir como alvo que não faz
# nada. Quem lê essas palavras é a receita do alvo de verdade.
.PHONY: $(ANOS_NA_LINHA)
todas abrir $(ANOS_NA_LINHA) $(VARIAVEL_INEP):
	@cd .

# A URL não entra numa linha de regra: `https://x` faria o make ler `https`
# como alvo e `//x` como pré-requisito. O curinga resolve sem citá-la, e só
# vale quando `map` está na linha — a validação lá de cima já barrou o que
# não for variável, ano, URL ou alvo conhecido.
ifneq (,$(filter map,$(MAKECMDGOALS)))
%:
	@cd .
endif

parquet:
	$(CENSO) parquet $(ANO)

amostra:
	$(strip $(CENSO) amostra $(ANO) $(OPCOES_AM))

# A URL vai entre aspas na receita pelo mesmo motivo de sempre: o `&`.
map:
	$(strip $(CENSO) map $(VARIAVEL_INEP) "$(URL_MALHA)" $(ANOS_NA_LINHA) $(OPCOES_MAP))

site:
	$(CENSO) site

servir:
	$(CENSO) servir

ibge-malhas:
	$(CENSO) malhas $(NIVEIS)

ibge-malha-municipal:
	$(CENSO) malhas municipio

# Sem anos: o dicionário cobre todos os que estiverem extraídos — é sobre o
# conjunto que ele fala. Os anos e as opções vêm dos modificadores lá de cima.
dicionario:
	$(CENSO) dicionario $(strip $(ANOS_DIC) $(OPCOES_DIC))

lab:
	$(CENSO) lab

test:
	$(CENSO) test

lint:
	$(CENSO) lint

limpar:
	$(CENSO) limpar

endif
