"""
================================================================================
PAINEL DE CONTROLE INTERATIVO DE MANUTENÇÃO (pipeline.py)
================================================================================
Objetivo:
  Fornecer um menu interativo de linha de comando no Windows (acionado pelo
  arquivo 'executar_pipeline.bat') para que o administrador possa executar
  qualquer etapa da arquitetura do CompraRibeirão com 1 clique:

  [1] Diagnóstico Completo do Sistema (Bancos Local, Público e IA)
  [2] Etapa 1: Descobrir Novas Lojas no Google Maps
  [3] Etapa 2A: Extrair Conteúdo Textual dos Sites das Lojas
  [4] Etapa 2B: Extrair Produtos Unitários de Lojas E-commerce
  [5] Etapa 3: Rodar IA Local (Qwen 2.5 via Ollama) nas Lojas
  [6] Etapa 4: Compilar Banco Leve para a Nuvem ('compraribeirao_publico.db')
  [7] Etapa 5: Publicar Atualização na Nuvem (GitHub -> Render.com)
  [8] RODAR ESTEIRA COMPLETA (Textos + IA Local + Compilar Banco Leve)
  [9] Iniciar Servidor Web Local (http://localhost:8000)
================================================================================
"""

import subprocess
import sys
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_python_executable() -> str:
    """Retorna o caminho do interpretador Python dentro da virtualenv do projeto."""
    venv_python = os.path.join(ROOT_DIR, "venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def main():
    venv_python = get_python_executable()

    while True:
        print("\n" + "=" * 68)
        print("      PAINEL DE CONTROLE E MANUTENÇÃO — COMPRA RIBEIRÃO (v2.5)")
        print("=" * 68)
        print(" [1] Ver Diagnóstico Completo (Status do Banco Bruto, IA e Nuvem)")
        print(" [2] Etapa 1 : Descobrir Novas Lojas no Google Maps")
        print(" [3] Etapa 2A: Extrair Textos Institucionais dos Sites (web_text_crawler)")
        print(" [4] Etapa 2B: Extrair Produtos de E-commerces (universal_crawler)")
        print(" [5] Etapa 3 : Rodar IA Local Qwen 2.5 via Ollama (enrich_with_llm)")
        print(" [6] Etapa 4 : Compilar Banco Leve da Nuvem (build_knowledge_base)")
        print(" [7] Etapa 5 : Subir Atualização para a Nuvem (GitHub -> Render)")
        print(" ------------------------------------------------------------------")
        print(" [8] ESTEIRA COMPLETA AUTOMÁTICA (Textos + IA + Compilar Banco Leve)")
        print(" [9] Iniciar Servidor Web Local (http://localhost:8000)")
        print(" [0] Sair")
        print("=" * 68)

        try:
            opt = input("\nEscolha uma opção [0 a 9]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo do Painel de Controle...")
            return

        if opt == "1":
            subprocess.run([venv_python, "backend/run_pipeline.py", "--step", "status"], cwd=ROOT_DIR)

        elif opt == "2":
            termo = input("\nDigite o setor/termo (ex: 'marmoraria') ou ENTER para varrer todos os 51 setores: ").strip()
            cmd = [venv_python, "backend/run_pipeline.py", "--step", "discover"]
            if termo:
                cmd.extend(["--query", termo])
            subprocess.run(cmd, cwd=ROOT_DIR)

        elif opt == "3":
            forcar = input("\nDeseja recapturar todos os sites do zero? [s/N] (ENTER = apenas novos): ").strip().lower()
            cmd = [venv_python, "backend/run_pipeline.py", "--step", "crawl-text"]
            if forcar == "s":
                cmd.append("--force")
            subprocess.run(cmd, cwd=ROOT_DIR)

        elif opt == "4":
            subprocess.run([venv_python, "backend/run_pipeline.py", "--step", "scrap"], cwd=ROOT_DIR)

        elif opt == "5":
            forcar = input("\nDeseja reprocessar TODAS as lojas na IA do zero? [s/N] (ENTER = apenas pendentes): ").strip().lower()
            cmd = [venv_python, "backend/run_pipeline.py", "--step", "enrich-ai"]
            if forcar == "s":
                cmd.append("--force")
            subprocess.run(cmd, cwd=ROOT_DIR)

        elif opt == "6":
            subprocess.run([venv_python, "backend/run_pipeline.py", "--step", "build-kb"], cwd=ROOT_DIR)

        elif opt == "7":
            msg = input("\nMensagem da atualização (ENTER para mensagem padrão): ").strip()
            cmd = [venv_python, "backend/run_pipeline.py", "--step", "deploy"]
            if msg:
                cmd.extend(["--msg", msg])
            subprocess.run(cmd, cwd=ROOT_DIR)

        elif opt == "8":
            termo = input("\nDeseja buscar um novo setor no Maps antes? Digite o termo (ou ENTER para pular Maps): ").strip()
            cmd = [venv_python, "backend/run_pipeline.py", "--step", "all"]
            if termo:
                cmd.extend(["--query", termo])
            subprocess.run(cmd, cwd=ROOT_DIR)

        elif opt == "9":
            print("\n[*] Iniciando servidor local em http://localhost:8000 ...")
            print("    (Pressione CTRL+C para parar o servidor e voltar ao menu)")
            try:
                subprocess.run(
                    [venv_python, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
                    cwd=ROOT_DIR
                )
            except KeyboardInterrupt:
                pass

        elif opt == "0":
            print("Encerrando Painel de Controle. Até logo!")
            return
        else:
            print("[!] Opção inválida. Digite um número de 0 a 9.")

        input("\nPressione ENTER para voltar ao menu principal...")


if __name__ == "__main__":
    main()
