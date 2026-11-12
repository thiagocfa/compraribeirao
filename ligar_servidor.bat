@echo off
cls
echo ========================================================
echo       INICIANDO SERVIDOR DO COMPRA RIBEIRAO
echo ========================================================
echo.
echo Acesse o site no seu navegador em: http://localhost:8000
echo Para encerrar o servidor, basta fechar esta janela ou apertar CTRL+C.
echo.
.\venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload
pause
