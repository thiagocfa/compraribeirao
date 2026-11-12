import subprocess
import sys
import os

def main():
    venv_python = os.path.join(os.path.dirname(__file__), "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    print("\n" + "=" * 56)
    print("      COMPRA RIBEIRÃO - PIPELINE DE EXTRAÇÃO")
    print("=" * 56)
    print("\nEscolha o que deseja executar:")
    print(" [1] Rodar Descoberta no Google Maps (Achar novas lojas)")
    print(" [2] Rodar Scrap dos Produtos (Extrair produtos dos sites)")
    print(" [3] Rodar Pipeline Completo (Descobrir + Extrair + Indexar)")
    print(" [4] Iniciar Servidor Web do Site (http://localhost:8000)")
    print(" [0] Sair")
    
    try:
        opt = input("\nDigite a opção [1, 2, 3, 4 ou 0]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    if opt == "1":
        termo = input("\nDigite o termo (ou aperte Enter para rodar os 15 setores padrão): ").strip()
        cmd = [venv_python, "backend/run_pipeline.py", "--step", "discover"]
        if termo:
            cmd.extend(["--query", termo])
        subprocess.run(cmd)

    elif opt == "2":
        cmd = [venv_python, "backend/run_pipeline.py", "--step", "scrap"]
        subprocess.run(cmd)

    elif opt == "3":
        termo = input("\nDigite o termo (ou aperte Enter para rodar os 15 setores padrão): ").strip()
        cmd = [venv_python, "backend/run_pipeline.py", "--step", "all"]
        if termo:
            cmd.extend(["--query", termo])
        subprocess.run(cmd)

    elif opt == "4":
        print("\nIniciando servidor em http://localhost:8000...")
        cmd = [venv_python, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]
        subprocess.run(cmd)

    elif opt == "0":
        print("Saindo...")
        return
    else:
        print("Opção inválida.")

if __name__ == "__main__":
    main()
