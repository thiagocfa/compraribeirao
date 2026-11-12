@echo off
cls
echo ========================================================
echo       COMPRARIBEIRÃO - COMPARTILHAR LINK PÚBLICO
echo ========================================================
echo.
echo Gerando link público e seguro (HTTPS Cloudflare)...
echo Aguarde alguns segundos...
echo.
.\cloudflared.exe tunnel --url http://127.0.0.1:8000
pause
