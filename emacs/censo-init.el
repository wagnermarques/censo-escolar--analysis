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

(dolist (pkg '(jupyter org))
  (unless (package-installed-p pkg)
    (package-refresh-contents)
    (package-install pkg)))

;; --------------------------------------------------------------------------
;; 2. Linguagens habilitadas no org-babel
;; --------------------------------------------------------------------------
(org-babel-do-load-languages
 'org-babel-load-languages
 '((python  . t)
   (jupyter . t)   ;; precisa vir por último na lista
   (shell   . t)
   (emacs-lisp . t)))

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
;; inline automáticas, sem completion do kernel.
;;
;; (setq org-babel-python-command "python3")
;; (setq org-babel-default-header-args:python
;;       '((:session . "censo") (:results . "output") (:exports . "both")))

;; --------------------------------------------------------------------------
;; 5. Atalho para sincronizar com o .ipynb
;; --------------------------------------------------------------------------
(defun censo-sync-notebooks ()
  "Sincroniza os pares .org/.ipynb do projeto atual."
  (interactive)
  (let* ((raiz (or (locate-dominating-file default-directory "pyproject.toml")
                   default-directory))
         (default-directory raiz))
    (compile "make sync")))

;; `C-c C-v ...' já é o prefixo do org-babel; usamos um prefixo livre.
(with-eval-after-load 'org
  (define-key org-mode-map (kbd "C-c n s") #'censo-sync-notebooks))

(provide 'censo-init)
;;; censo-init.el ends here
