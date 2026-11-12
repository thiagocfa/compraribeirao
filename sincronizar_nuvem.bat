@echo off
chcp 65001 > nul
echo ======================================================
echo    COMPRARIBEIRAO - SINCRONIZAR COM A NUVEM
echo ======================================================
echo.
echo 1. Indexando dados e arquivos modificados...
git add .
echo.
set /p msg="Mensagem da atualizacao (pressione ENTER para padrao): "
if "%msg%"=="" set msg="Atualizacao automatica do catalogo e codigo"
git commit -m "%msg%"
echo.
echo 2. Enviando atualizacao para a nuvem...
git push origin main
echo.
echo ======================================================
echo    SINCRONIZACAO CONCLUIDA COM SUCESSO!
echo ======================================================
pause
