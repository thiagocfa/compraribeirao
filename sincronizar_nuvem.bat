@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
echo ======================================================
echo    COMPRARIBEIRAO - SINCRONIZAR COM A NUVEM (GITHUB)
echo ======================================================
echo.
echo 1. Salvando dados locais e produtos minerados...
git add .
echo.
set "msg="
set /p "msg=Mensagem da atualizacao (pressione ENTER para padrao): "
if not defined msg set "msg=Atualizacao automatica do catalogo e codigo"

git diff --cached --quiet
if %errorlevel% neq 0 (
    git commit -m "!msg!"
) else (
    echo Nenhum arquivo modificado para commitar.
)

echo.
echo 2. Enviando para o GitHub...
git push github main
if %errorlevel% equ 0 (
    echo.
    echo ======================================================
    echo    SINCRONIZACAO CONCLUIDA COM SUCESSO!
    echo ======================================================
) else (
    echo.
    echo ======================================================
    echo    FALHA AO ENVIAR PARA O GITHUB.
    echo ======================================================
)
pause
