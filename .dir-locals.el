;;; Variáveis locais do projeto censo-escolar.
;;; O Emacs pergunta antes de aplicar valores "inseguros" — responda `!' uma vez
;;; para marcar este projeto como confiável.

((nil . ((fill-column . 88)))

 (org-mode
  . ((org-confirm-babel-evaluate . nil)
     ;; Blocos rodam a partir da raiz do projeto, não de notebooks/.
     ;; Assim os caminhos relativos batem com o que o Jupyter enxerga.
     (org-babel-default-header-args
      . ((:session . "censo")
         (:async   . "yes")
         (:exports . "both")))))

 (python-mode . ((indent-tabs-mode . nil)
                 (python-indent-offset . 4))))
