# Instalador Windows — Titan Cut

## Como usar

1. Baixe/clone o repositório `titancut` inteiro (ou um pacote com a pasta
   `installer/windows` e `src` lado a lado).
2. Dê duplo clique em **`Instalar_Titan_Cut.bat`**.
3. O instalador copia `src/Titan Cut.py` e `src/Modules/*.py` para:
   `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit`
4. Ele também tenta instalar as dependências Python do motor de análise
   (`opencv-python`, `numpy`) no mesmo Python que o Resolve usa pra rodar
   scripts — não um Python embarcado/venv, mas o Python do sistema (via
   `py -3` ou `python` no PATH).
5. Abra o DaVinci Resolve → `Workspace > Scripts > Edit > Titan Cut`.

## Pré-requisitos

- **Python 3** instalado no Windows, com a opção "Add python.exe to PATH"
  marcada na instalação (baixe em python.org se não tiver).
  Sem isso, o instalador avisa e você precisa instalar o Python manualmente
  antes de rodar o instalador de novo.
- DaVinci Resolve (Free ou Studio) já instalado pelo menos uma vez, pra pasta
  `Support\Fusion\Scripts` já existir (o instalador cria o resto se faltar).

## Rodar de novo pra atualizar

É só rodar o `.bat` de novo — ele sobrescreve os arquivos do plugin. Feche o
painel Titan Cut no Resolve antes (os arquivos ficam com o processo do
Resolve, copiar por cima enquanto está aberto pode falhar em alguns casos).

## Desinstalar

Apague manualmente:
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\Titan Cut.py`
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\Modules\titan_cut_engine.py`
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\Modules\titan_cut_locale.py`

(Não apaga a pasta `Modules` inteira automaticamente pra não arriscar
remover arquivos de outro plugin que também a use.)
