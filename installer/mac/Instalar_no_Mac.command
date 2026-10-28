#!/bin/bash
set -euo pipefail

# Instalador Titan Cut (macOS) — copia src/ pra pasta de Scripts do Resolve
# e tenta instalar as dependências Python do motor (opencv-python, numpy).
#
# AVISO DE ENGENHARIA: não testado rodando de verdade num Mac — escrito
# seguindo o mesmo padrão já validado em produção no Instalar_no_Mac.command
# do titan-titulos (mesmos caminhos TARGET/STORE, mesma lógica de symlink
# guard), mas a parte de detectar/instalar opencv-python e numpy é nova e
# ainda não foi exercitada. Testar na primeira execução real.

DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
# Suporta rodar de dentro do repo clonado (installer/mac/../../src) ou de um
# pacote distribuído com "Arquivos" ao lado do .command
SRC="$DIR/../../src"
[ -f "$SRC/Titan Cut.py" ] || SRC="$DIR/Arquivos"
if [ ! -f "$SRC/Titan Cut.py" ]; then
    /usr/bin/osascript -e 'display alert "Titan Cut" message "Não encontrei \"Titan Cut.py\". Extraia o pacote inteiro (ou rode de dentro do repositório titancut) antes de instalar." as critical'
    exit 1
fi

TARGET="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit"
STORE="$HOME/Library/Containers/com.blackmagic-design.DaVinciResolveApp/Data/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit"

printf '\033[38;2;56;189;248m\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n  TITAN CUT — instalador macOS\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n'

/usr/bin/osascript -e 'display dialog "Instalar o Titan Cut no DaVinci Resolve?\n\nFeche o Resolve antes de instalar." with title "Titan Cut" buttons {"Cancelar", "Instalar"} default button "Instalar" cancel button "Cancelar"' >/dev/null || exit 0

validate() {
    case "$1" in "$TARGET"|"$STORE") ;; *) echo 'Destino inesperado.'; exit 1;; esac
    local current="$1"
    while [ "$current" != / ]; do
        if [ -L "$current" ]; then echo 'Pasta redirecionada; instalação interrompida.'; exit 1; fi
        current=$(dirname "$current")
    done
}

install_target() {
    local target="$1"
    validate "$target"
    mkdir -p "$target/Modules"
    local backup
    backup=$(mktemp -d "${TMPDIR:-/tmp}/titancut-backup-XXXXXXXX")
    [ ! -f "$target/Titan Cut.py" ] || cp -p "$target/Titan Cut.py" "$backup/" 2>/dev/null || true
    [ ! -d "$target/Modules" ] || cp -R "$target/Modules" "$backup/" 2>/dev/null || true

    if ! (cp "$SRC/Titan Cut.py" "$target/Titan Cut.py" \
        && cp "$SRC/Modules/titan_cut_engine.py" "$target/Modules/titan_cut_engine.py" \
        && cp "$SRC/Modules/titan_cut_locale.py" "$target/Modules/titan_cut_locale.py"); then
        [ ! -f "$backup/Titan Cut.py" ] || cp "$backup/Titan Cut.py" "$target/"
        [ ! -d "$backup/Modules" ] || cp -R "$backup/Modules/." "$target/Modules/"
        echo "Falha ao copiar pra $target. Backup: $backup"
        return 1
    fi
    printf '✓ Instalado em: %s\n  Backup do anterior: %s\n' "$target" "$backup"
}

install_target "$TARGET"
if [ -d "$HOME/Library/Containers/com.blackmagic-design.DaVinciResolveApp" ]; then
    install_target "$STORE"
fi

# --- Dependências Python (opencv-python, numpy) -----------------------
# O Resolve roda os scripts com o Python 3 do sistema (não um venv). No
# macOS normalmente é o /usr/bin/python3 do Xcode Command Line Tools ou um
# python3 instalado via python.org/Homebrew — tentamos o que estiver no
# PATH primeiro.
printf '\nVerificando Python e dependências (opencv-python, numpy)...\n'
PYBIN=""
for cand in python3 /usr/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        PYBIN="$cand"
        break
    fi
done

if [ -z "$PYBIN" ]; then
    /usr/bin/osascript -e 'display dialog "Não encontrei um python3 instalado.\n\nO Titan Cut precisa de Python 3 com opencv-python e numpy pra funcionar dentro do Resolve. Instale o Python 3 (python.org ou Homebrew: brew install python) e rode este instalador de novo." with title "Titan Cut" buttons {"OK"} default button "OK"' >/dev/null
else
    echo "Usando: $PYBIN"
    if "$PYBIN" -m pip install --user --upgrade opencv-python numpy; then
        echo "✓ Dependências instaladas/atualizadas."
    else
        echo "[AVISO] pip install falhou. Rode manualmente: $PYBIN -m pip install --user opencv-python numpy"
    fi
fi

/usr/bin/osascript -e 'display dialog "Instalado!\n\nNo DaVinci Resolve: Workspace > Scripts > Edit > Titan Cut." with title "Titan Cut" buttons {"Concluir"} default button "Concluir"' >/dev/null || true
