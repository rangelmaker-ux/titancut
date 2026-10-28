@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Titan Cut — Instalador (Windows)

echo ============================================
echo   Titan Cut — Instalador para DaVinci Resolve
echo ============================================
echo.

rem --- Pasta deste instalador (funciona rodando de qualquer lugar) -------
set "HERE=%~dp0"

rem --- Localiza a pasta de origem (src/) --------------------------------
rem Suporta duas disposições:
rem   1) Rodando direto do repositório clonado (installer\windows\..\..\src)
rem   2) Rodando de um pacote distribuído com "Arquivos\" ao lado do .bat
set "SRC=%HERE%..\..\src"
if not exist "%SRC%\Titan Cut.py" set "SRC=%HERE%Arquivos"
if not exist "%SRC%\Titan Cut.py" (
    echo [ERRO] Nao encontrei "Titan Cut.py" nem em "%HERE%..\..\src" nem em "%HERE%Arquivos".
    echo        Extraia o pacote inteiro antes de instalar, ou rode este .bat de dentro do repositorio titancut.
    pause
    exit /b 1
)

rem --- Pasta de destino dos Scripts do Resolve ---------------------------
set "TARGET=%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit"

echo Origem:  %SRC%
echo Destino: %TARGET%
echo.

if not exist "%TARGET%" (
    echo Criando pasta de destino...
    mkdir "%TARGET%" >nul 2>&1
)
if not exist "%TARGET%\Modules" (
    mkdir "%TARGET%\Modules" >nul 2>&1
)

echo Copiando arquivos...
copy /Y "%SRC%\Titan Cut.py" "%TARGET%\Titan Cut.py" >nul
if errorlevel 1 (
    echo [ERRO] Falha ao copiar "Titan Cut.py". Feche o DaVinci Resolve e tente novamente.
    pause
    exit /b 1
)
copy /Y "%SRC%\Modules\titan_cut_engine.py" "%TARGET%\Modules\titan_cut_engine.py" >nul
copy /Y "%SRC%\Modules\titan_cut_locale.py" "%TARGET%\Modules\titan_cut_locale.py" >nul
echo   OK — arquivos do plugin copiados.
echo.

rem --- Dependências Python (opencv-python, numpy) ------------------------
rem O Resolve roda os scripts com o Python do sistema (nao um venv), entao
rem instalamos as dependencias nesse mesmo Python. Tenta "py -3" primeiro
rem (launcher oficial do python.org), depois "python" no PATH.
echo Verificando Python e dependencias (opencv-python, numpy)...
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)

if not defined PYCMD (
    echo [AVISO] Nao encontrei um Python instalado no sistema ^(nem "py -3" nem "python" no PATH^).
    echo         O Titan Cut PRECISA de Python 3 com opencv-python e numpy instalados pra funcionar
    echo         dentro do Resolve. Instale o Python de https://www.python.org/downloads/windows/
    echo         marcando "Add python.exe to PATH" na instalacao, depois rode este instalador de novo
    echo         ^(ou abra um terminal e rode: pip install opencv-python numpy^).
    echo.
    goto :done
)

echo   Usando: %PYCMD%
%PYCMD% -m pip install --user --upgrade opencv-python numpy
if errorlevel 1 (
    echo [AVISO] "pip install" falhou. Rode manualmente num terminal:
    echo         %PYCMD% -m pip install --user opencv-python numpy
) else (
    echo   OK — dependencias instaladas/atualizadas.
)

:done
echo.
echo ============================================
echo   Instalacao concluida.
echo   Abra o DaVinci Resolve e va em:
echo   Workspace ^> Scripts ^> Edit ^> Titan Cut
echo ============================================
echo.
pause
exit /b 0
