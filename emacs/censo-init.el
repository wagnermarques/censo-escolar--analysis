;;; censo-init.el --- Configuração Emacs para o projeto censo-escolar  -*- lexical-binding: t; -*-

;; Carregue com:  (load-file "/caminho/para/o/projeto/emacs/censo-init.el")
;; ou copie os trechos que interessarem para o seu init.el.
;;
;; O objetivo é fazer os blocos `jupyter-python' dos arquivos .org rodarem no
;; MESMO kernel Jupyter que o pessoal do notebook usa. Não é uma reimplementação
;; do Python dentro do Emacs: é o kernel de verdade, falado pelo protocolo do
;; Jupyter. É por isso que a base de código pode ser única.

;;; Code:

;; --------------------------------------------------------------------------
;; 1. Pacotes
;; --------------------------------------------------------------------------
;; `jupyter' (emacs-jupyter) exige que o Emacs tenha sido compilado com suporte
;; a módulos dinâmicos e que `zmq' consiga compilar. Em Fedora:
;;
;;     sudo dnf install zeromq-devel libtool autoconf automake make gcc
;;
;; Alternativa mais leve, sem ZeroMQ: `ob-jupyter' via `jupyter' não; use
;; então blocos `python' simples com :session (veja a seção 4).

(require 'package)
(add-to-list 'package-archives '("melpa" . "https://melpa.org/packages/") t)

;; `emacs -q' pula o init.el E o `package-activate-all' do startup. Sem isto o
;; ~/.emacs.d/elpa não entra no load-path e o `ob-jupyter' some, mesmo estando
;; instalado. Idempotente: se o seu init.el já ativou, não custa nada.
(package-activate-all)

(dolist (pkg '(jupyter org))
  (unless (package-installed-p pkg)
    (package-refresh-contents)
    (package-install pkg)))

;; --------------------------------------------------------------------------
;; 1b. Onde mora o `jupyter' deste projeto
;; --------------------------------------------------------------------------
;; O emacs-jupyter não fala com o kernel sozinho: ele chama o executável
;; `jupyter' para descobrir os kernelspecs. Neste computador ele só existe
;; dentro do .venv, então apontamos para lá em vez de contar com o PATH.
(defvar censo-raiz
  (let ((aqui (or (and load-file-name (file-name-directory load-file-name))
                  default-directory)))
    (or (locate-dominating-file aqui "pyproject.toml")
        (expand-file-name ".." aqui)))
  "Raiz do projeto censo-escolar.")

(let ((venv-bin (expand-file-name ".venv/bin" censo-raiz)))
  (when (file-directory-p venv-bin)
    ;; exec-path é o que o Emacs usa; PATH é o que os subprocessos herdam.
    (add-to-list 'exec-path venv-bin)
    (setenv "PATH" (concat venv-bin path-separator (getenv "PATH")))
    (setq jupyter-executable (expand-file-name "jupyter" venv-bin))))

;; --------------------------------------------------------------------------
;; 2. Linguagens habilitadas no org-babel
;; --------------------------------------------------------------------------
;; Se o emacs-jupyter não estiver disponível (zmq não compilou, por exemplo),
;; degrada para blocos `python' comuns em vez de abortar o arquivo inteiro.
;; Duas condições, e as duas já morderam este projeto: o `ob-jupyter' precisa
;; estar no load-path (pacote ativado) E o módulo binário emacs-zmq precisa ter
;; sido compilado — sem ele o kernel sobe mas a conversa morre em `zmq-REQ'.
(defvar censo-jupyter-disponivel
  (and (locate-library "ob-jupyter")
       module-file-suffix
       (locate-file "emacs-zmq" load-path (list module-file-suffix))
       t)
  "Não-nil quando os blocos `jupyter-python' podem ser usados.")

(org-babel-do-load-languages
 'org-babel-load-languages
 `((python  . t)
   (shell   . t)
   (emacs-lisp . t)
   ;; `jupyter' precisa vir por último na lista.
   ,@(when censo-jupyter-disponivel '((jupyter . t)))))

(unless censo-jupyter-disponivel
  (message "censo-init: %s ausente; caindo para blocos `python' (seção 4)."
           (if (locate-library "ob-jupyter")
               "módulo emacs-zmq (rode `make -C ~/.emacs.d/elpa/zmq-*')"
             "ob-jupyter")))

;; Não perguntar a cada execução. Só faz sentido porque este é o SEU projeto;
;; não coloque isso globalmente se você abre .org de terceiros.
(setq org-confirm-babel-evaluate nil)

;; Mostrar imagens geradas logo após a execução do bloco.
(add-hook 'org-babel-after-execute-hook #'org-display-inline-images 'append)
(setq org-image-actual-width '(700))

;; Realce de sintaxe e TAB nativo dentro dos blocos.
(setq org-src-fontify-natively t
      org-src-tab-acts-natively t
      org-src-preserve-indentation t
      org-edit-src-content-indentation 0)

;; --------------------------------------------------------------------------
;; 3. Argumentos de cabeçalho padrão
;; --------------------------------------------------------------------------
;; :session   -> estado persiste entre blocos, como num notebook
;; :async yes -> o Emacs não trava enquanto o pandas mói os dados
;; :results   -> "value" devolve o valor da última expressão, como o Jupyter
(setq org-babel-default-header-args:jupyter-python
      '((:session . "censo")
        (:async   . "yes")
        (:kernel  . "python3")
        (:results . "value")
        (:exports . "both")))

;; --------------------------------------------------------------------------
;; 4. Plano B: blocos `python' comuns (sem emacs-jupyter)
;; --------------------------------------------------------------------------
;; Funciona sem ZeroMQ, mas é mais limitado: sem saída rica, sem imagens
;; inline automáticas, sem completion do kernel. Ligado sozinho enquanto o
;; emacs-zmq não estiver compilado, para o projeto não ficar parado.

(setq org-babel-python-command
      (let ((py (expand-file-name ".venv/bin/python" censo-raiz)))
        (if (file-executable-p py) py "python3")))

(unless censo-jupyter-disponivel
  (setq org-babel-default-header-args:python
        '((:session . "censo")
          (:results . "output")
          (:exports . "both"))))

;; --------------------------------------------------------------------------
;; 5. Atalho para sincronizar com o .ipynb
;; --------------------------------------------------------------------------
(defun censo-sync-notebooks ()
  "Sincroniza os pares .org/.ipynb do projeto atual."
  (interactive)
  (let* ((raiz (or (locate-dominating-file default-directory "pyproject.toml")
                   default-directory))
         (default-directory raiz))
    (compile "uv run orgnb sync")))

;; `C-c C-v ...' já é o prefixo do org-babel; usamos um prefixo livre.
(with-eval-after-load 'org
  (define-key org-mode-map (kbd "C-c n s") #'censo-sync-notebooks))

(provide 'censo-init)
;;; censo-init.el ends here
