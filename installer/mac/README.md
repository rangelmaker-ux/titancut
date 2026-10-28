# Instalador macOS — Titan Cut

## Como usar

1. Baixe/clone o repositório `titancut` inteiro.
2. Dê duplo clique em **`Instalar_no_Mac.command`** (se o Gatekeeper bloquear
   por ser de "desenvolvedor não identificado", clique com Ctrl no arquivo →
   Abrir → Abrir, uma vez).
3. Confirme no diálogo. Ele copia `src/Titan Cut.py` e `src/Modules/*.py`
   pra pasta de Scripts do Resolve (cobre tanto a instalação normal quanto a
   sandboxed da App Store, se existir) e tenta instalar `opencv-python` e
   `numpy` no Python 3 do sistema.
4. Abra o DaVinci Resolve → `Workspace > Scripts > Edit > Titan Cut`.

## Pré-requisitos

- **Python 3** instalado (`python3` no PATH — já vem com as Command Line
  Tools do Xcode, ou instale via python.org/Homebrew).
- DaVinci Resolve já instalado pelo menos uma vez.

## Desinstalar

Apague manualmente de
`~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit`:
- `Titan Cut.py`
- `Modules/titan_cut_engine.py`
- `Modules/titan_cut_locale.py`
