@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
title CompraRibeirao - Sincronizar com a Nuvem (GitHub / Render)
echo ====================================================================
echo    COMPRARIBEIRAO - ATUALIZAR BANCO LEVE E ENVIAR PARA A NUVEM
echo ====================================================================
echo.
set /p "compilar=Deseja recompilar o banco leve (compraribeirao_publico.db) antes de subir? [S/n]: "
if /I not "%compilar%"=="n" (
    echo.
    echo [1/2] Compilando banco leve a partir dos dados locais...
    .\venv\Scripts\python.exe backend\build_knowledge_base.py
)

echo.
set "msg="
set /p "msg=Mensagem da atualizacao (pressione ENTER para padrao): "
if not defined msg set "msg=Atualizacao do catalogo inteligente e codigo"

echo.
echo [2/2] Enviando banco leve (compraribeirao_publico.db) e codigos para o GitHub...
.\venv\Scripts\python.exe backend\run_pipeline.py --step deploy --msg "!msg!"
echo.
pause
