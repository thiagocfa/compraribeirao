@echo off
chcp 65001 > nul
echo ======================================================
echo    COMPRARIBEIRAO - SINCRONIZAR COM A NUVEM (GITHUB)
echo ======================================================
echo.
echo 1. Salvando dados locais e produtos minerados...
git add .
echo.
set /p msg="Mensagem da atualizacao (pressione ENTER para padrao): "
if "%msg%"=="" set msg="Atualizacao automatica do catalogo e codigo"
git commit -m "%msg%"
echo.
echo 2. Enviando para o GitHub...
git push github main
echo.
echo ======================================================
echo    SINCRONIZACAO CONCLUIDA COM SUCESSO!
echo ======================================================
pause
