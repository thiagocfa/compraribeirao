@echo off
cls
echo ========================================================
echo       COMPRA RIBEIRAO - PIPELINE DE EXTRACAO
echo ========================================================
echo.
echo Escolha o que deseja executar:
echo [1] Rodar Descoberta no Google Maps
echo [2] Rodar Scrap dos Produtos (Extrair produtos dos sites)
echo [3] Rodar Pipeline Completo (Descobrir + Extrair + Indexar)
echo [4] Iniciar Servidor Web do Site (http://localhost:8000)
echo.
set /p opt="Digite a opcao [1, 2, 3 ou 4]: "

if "%opt%"=="1" (
    echo.
    set /p termo="Digite o setor/termo (ou Enter para rodar os 15 padroes): "
    if "%termo%"=="" (
        .\venv\Scripts\python.exe backend\run_pipeline.py --step discover
    ) else (
        .\venv\Scripts\python.exe backend\run_pipeline.py --step discover --query "%termo%"
    )
)

if "%opt%"=="2" (
    echo.
    echo Iniciando extracao de produtos dos sites...
    .\venv\Scripts\python.exe backend\run_pipeline.py --step scrap
)

if "%opt%"=="3" (
    echo.
    set /p termo="Digite o setor/termo (ou Enter para rodar os 15 padroes): "
    if "%termo%"=="" (
        .\venv\Scripts\python.exe backend\run_pipeline.py --step all
    ) else (
        .\venv\Scripts\python.exe backend\run_pipeline.py --step all --query "%termo%"
    )
)

if "%opt%"=="4" (
    echo.
    echo Iniciando servidor em http://localhost:8000...
    .\venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload
)

pause
