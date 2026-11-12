"""
================================================================================
ORQUESTRADOR CENTRAL DA ESTEIRA DE MANUTENÇÃO (backend/run_pipeline.py)
================================================================================
Objetivo:
  Unificar todas as etapas de manutenção do CompraRibeirão em um único script CLI
  que pode ser chamado tanto pelo Painel de Controle no Windows ('executar_pipeline.bat'
  e 'pipeline.py') quanto pelo Painel de Controle Web ('/api/admin/run-step').

Etapas Disponíveis (--step):
  1. 'status'     : Exibe o diagnóstico completo do banco bruto, IA, banco público e Ollama.
  2. 'discover'   : Busca novas lojas físicas no Google Maps (por termo ou 51 setores).
  3. 'crawl-text' : Visita os sites das lojas e salva todo o texto institucional.
  4. 'scrap'      : Extrai produtos de lojas que possuem e-commerce (Tray, VTEX, etc.).
  5. 'enrich-ai'  : Roda a IA local Qwen 2.5 (via Ollama) para categorizar e resumir lojas.
  6. 'build-kb'   : Compila o banco leve 'compraribeirao_publico.db' (~3 MB) para a nuvem.
  7. 'deploy'     : Envia o banco leve compilado e o código para o GitHub (atualiza o Render).
  8. 'all'        : Executa a esteira completa (Textos -> IA -> Compilar Banco Público).
================================================================================
"""

import asyncio
import sys
import os
import subprocess
import sqlite3
import httpx

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(ROOT_DIR)
sys.path.append(BACKEND_DIR)

from backend.database import RAW_DB_PATH, PUBLIC_DB_PATH, init_db
from backend.search_terms import list_search_terms, init_search_terms
from backend.discovery_gmaps import scrape_google_maps_stores
from backend.crawlers.web_text_crawler import crawl_all_store_texts, sync_discovered_to_stores
from backend.crawlers.universal_crawler import ingest_all_discovered_with_websites
from backend.enrich_with_llm import run_enrichment, OLLAMA_BASE_URL, MODEL_NAME
from backend.build_knowledge_base import build_knowledge_base


def get_system_diagnostics() -> dict:
    """
    Coleta todas as métricas de saúde e preenchimento dos bancos local e público,
    além do status do motor de IA Ollama.
    """
    diag = {
        "raw_db_exists": os.path.exists(RAW_DB_PATH),
        "raw_db_size_mb": round(os.path.getsize(RAW_DB_PATH) / (1024 * 1024), 2) if os.path.exists(RAW_DB_PATH) else 0,
        "public_db_exists": os.path.exists(PUBLIC_DB_PATH),
        "public_db_size_mb": round(os.path.getsize(PUBLIC_DB_PATH) / (1024 * 1024), 2) if os.path.exists(PUBLIC_DB_PATH) else 0,
        "discovered_count": 0,
        "stores_count": 0,
        "stores_with_website": 0,
        "web_text_success": 0,
        "web_text_pending": 0,
        "ai_enriched_count": 0,
        "ai_pending_count": 0,
        "raw_products_count": 0,
        "public_stores_count": 0,
        "public_neighborhoods_count": 0,
        "public_leads_count": 0,
        "ollama_online": False,
        "ollama_model": MODEL_NAME,
    }

    # 1. Consulta o banco bruto local (se existir no PC)
    if diag["raw_db_exists"]:
        try:
            conn = sqlite3.connect(RAW_DB_PATH)
            c = conn.cursor()

            def safe_count(query: str) -> int:
                try:
                    c.execute(query)
                    row = c.fetchone()
                    return row[0] if row else 0
                except Exception:
                    return 0

            diag["discovered_count"] = safe_count("SELECT COUNT(*) FROM discovered_stores")
            diag["stores_count"] = safe_count("SELECT COUNT(*) FROM stores")
            diag["stores_with_website"] = safe_count("SELECT COUNT(*) FROM stores WHERE website IS NOT NULL AND website != ''")
            diag["web_text_success"] = safe_count("SELECT COUNT(*) FROM store_web_content WHERE status = 'success'")
            diag["ai_enriched_count"] = safe_count("SELECT COUNT(*) FROM store_ai_intelligence")
            diag["raw_products_count"] = safe_count("SELECT COUNT(*) FROM products")

            # Quantas lojas têm site mas ainda não têm texto capturado
            diag["web_text_pending"] = safe_count("""
                SELECT COUNT(*) FROM stores s
                LEFT JOIN store_web_content w ON s.id = w.store_id
                WHERE s.website IS NOT NULL AND s.website != '' AND (w.status IS NULL OR w.status != 'success')
            """)

            # Quantas lojas têm texto capturado mas ainda não passaram pela IA
            diag["ai_pending_count"] = safe_count("""
                SELECT COUNT(*) FROM stores s
                JOIN store_web_content w ON s.id = w.store_id
                LEFT JOIN store_ai_intelligence ai ON s.id = ai.store_id
                WHERE w.status = 'success' AND ai.store_id IS NULL
            """)
            conn.close()
        except Exception:
            pass

    # 2. Consulta o banco público leve (usado pelo site e enviado à nuvem)
    if diag["public_db_exists"]:
        try:
            conn = sqlite3.connect(PUBLIC_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM stores")
            diag["public_stores_count"] = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT neighborhood) FROM stores")
            diag["public_neighborhoods_count"] = c.fetchone()[0]
            try:
                c.execute("SELECT COUNT(*) FROM lead_clicks")
                diag["public_leads_count"] = c.fetchone()[0]
            except Exception:
                diag["public_leads_count"] = 0
            conn.close()
        except Exception:
            pass

    # 3. Verifica se o servidor Ollama está respondendo na porta 11434
    try:
        r = httpx.get(OLLAMA_BASE_URL, timeout=1.5)
        diag["ollama_online"] = (r.status_code == 200)
    except Exception:
        diag["ollama_online"] = False

    return diag


def print_status_report():
    """Exibe no terminal um painel visual com o diagnóstico completo do projeto."""
    d = get_system_diagnostics()
    print("\n" + "=" * 68)
    print("   DIAGNÓSTICO DE MANUTENÇÃO — COMPRARIBEIRÃO (v2.5)")
    print("=" * 68)
    print(f" [CAMADA 1: BANCO BRUTO LOCAL - compraribeirao.db]")
    print(f"   • Status do Arquivo       : {'Presente (' + str(d['raw_db_size_mb']) + ' MB)' if d['raw_db_exists'] else 'Ausente'}")
    print(f"   • Lojas Descobertas (Maps): {d['discovered_count']} estabelecimentos")
    print(f"   • Lojas na Base Mestre    : {d['stores_count']} lojas ({d['stores_with_website']} com site)")
    print(f"   • Textos dos Sites Salvos : {d['web_text_success']} extraídos ({d['web_text_pending']} pendentes)")
    print(f"   • Analisadas pela IA Local: {d['ai_enriched_count']} enriquecidas ({d['ai_pending_count']} na fila da IA)")
    print(f"   • Produtos de E-commerce  : {d['raw_products_count']} produtos unitários")
    print(f"   • Motor Ollama ({d['ollama_model']}) : {'ONLINE (127.0.0.1:11434)' if d['ollama_online'] else 'Pronto (inicia automaticamente ao rodar IA)'}")
    print("-" * 68)
    print(f" [CAMADA 2: BANCO PÚBLICO DA NUVEM - compraribeirao_publico.db]")
    print(f"   • Tamanho Ultraleve       : {d['public_db_size_mb']} MB (limite ideal < 10 MB para Render Free)")
    print(f"   • Lojas Publicadas no Site: {d['public_stores_count']} lojas físicas indexadas em FTS5")
    print(f"   • Bairros Padronizados    : {d['public_neighborhoods_count']} bairros de Ribeirão Preto")
    print(f"   • Cliques Rastreados      : {d['public_leads_count']} leads gerados (WhatsApp/GPS/Site)")
    print("=" * 68 + "\n")


async def run_discovery_step(query: str = None, max_per_term: int = 25):
    """Etapa 1: Descoberta de lojas físicas no Google Maps + Sincronização com tabela 'stores'."""
    init_db()
    init_search_terms()
    if query:
        print(f"\n================================================================")
        print(f" ETAPA 1: Buscando lojas para '{query}' no Google Maps...")
        print(f"================================================================")
        await scrape_google_maps_stores(query, max_results=max_per_term)
    else:
        terms = list_search_terms()
        active_terms = [t for t in terms if t.get("active")]
        print(f"\n================================================================")
        print(f" ETAPA 1: Varrendo {len(active_terms)} setores comerciais de Ribeirão Preto...")
        print(f"================================================================")
        for t in active_terms:
            term_text = t["term"]
            print(f"\n[>] Setor: {t['category']} ('{term_text}')...")
            await scrape_google_maps_stores(term_text, max_results=max_per_term)

    synced = sync_discovered_to_stores()
    print(f"[✓] {synced} lojas sincronizadas para a base principal ('stores').")


async def run_scraping_step():
    """Etapa 2B: Extração de produtos unitários para lojas que possuem plataforma de e-commerce."""
    print(f"\n================================================================")
    print(f" ETAPA 2B: Extraindo produtos de lojas com e-commerce...")
    print(f"================================================================")
    await ingest_all_discovered_with_websites()


def deploy_to_cloud(commit_msg: str = "chore: atualizacao do banco de inteligencia e sistema"):
    """
    Etapa 5: Publica o banco leve ('compraribeirao_publico.db') e os arquivos de código
    no GitHub (branch 'main'), disparando o deploy automático no Render.com.
    NUNCA envia o banco bruto de 415 MB ('compraribeirao.db').
    """
    print("\n" + "=" * 64)
    print("   ETAPA 5: PUBLICANDO ATUALIZAÇÃO NA NUVEM (GITHUB -> RENDER)")
    print("=" * 64)

    try:
        # 1. Garante que apenas os arquivos públicos e de código sejam adicionados
        files_to_stage = [
            "compraribeirao_publico.db",
            "backend",
            "frontend",
            "DOCUMENTACAO_DO_PROJETO.md",
            "README.md",
            "Dockerfile",
            "requirements.txt",
            ".gitignore",
            ".gitattributes",
            "pipeline.py",
            "executar_pipeline.bat",
            "sincronizar_nuvem.bat",
            "ligar_servidor.bat",
        ]
        existing_files = [f for f in files_to_stage if os.path.exists(os.path.join(ROOT_DIR, f))]
        subprocess.run(["git", "add"] + existing_files, cwd=ROOT_DIR, check=True)

        # 2. Verifica se há alterações para commitar
        diff_res = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT_DIR)
        if diff_res.returncode != 0:
            print(f"[*] Criando commit: '{commit_msg}'...")
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=ROOT_DIR, check=True)
        else:
            print("[i] Nenhum arquivo novo para commitar. Verificando sincronização com o GitHub...")

        # 3. Envia para o repositório remoto 'github' na branch 'main'
        print("[*] Enviando para o GitHub (git push github main)...")
        push_res = subprocess.run(["git", "push", "github", "main"], cwd=ROOT_DIR, capture_output=True, text=True)
        if push_res.returncode == 0:
            print("[✓] SUCESSO! Banco público e códigos enviados ao GitHub.")
            print("    O Render.com atualizará https://compraribeirao.onrender.com/ automaticamente em ~2 minutos.")
            return True
        else:
            print(f"[!] Erro no git push:\n{push_res.stderr}")
            return False
    except Exception as e:
        print(f"[!] Falha ao publicar na nuvem: {e}")
        return False


async def run_full_pipeline(query: str = None, force_ai: bool = False):
    """
    Executa a esteira completa de atualização inteligente:
      1. Se foi informado um termo (query), busca novas lojas no Google Maps.
      2. Extrai os conteúdos textuais dos sites de todas as lojas pendentes.
      3. Roda a IA local (Qwen 2.5 via Ollama) para interpretar e categorizar as lojas.
      4. Compila o banco leve 'compraribeirao_publico.db' (~3.10 MB) pronto para uso!
    """
    if query:
        await run_discovery_step(query)

    print("\n---> [PASSO 1/3] Extraindo textos institucionais dos websites...")
    await crawl_all_store_texts()

    print("\n---> [PASSO 2/3] Interpretando lojas com IA Local (Qwen 2.5)...")
    run_enrichment(force_reprocess=force_ai)

    print("\n---> [PASSO 3/3] Compilando Knowledge Base leve ('compraribeirao_publico.db')...")
    build_knowledge_base()

    print("\n" + "=" * 64)
    print(" [✓] ESTEIRA COMPLETA FINALIZADA COM SUCESSO!")
    print("     O banco 'compraribeirao_publico.db' já está atualizado.")
    print("=" * 64)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Orquestrador de Manutenção do CompraRibeirão")
    parser.add_argument(
        "--step",
        choices=["status", "discover", "crawl-text", "scrap", "enrich-ai", "build-kb", "deploy", "all"],
        default="status",
        help="Qual etapa de manutenção executar"
    )
    parser.add_argument("--query", type=str, default=None, help="Termo específico para descobrir no Google Maps")
    parser.add_argument("--limit", type=int, default=None, help="Limite de itens a processar na etapa")
    parser.add_argument("--force", action="store_true", help="Forçar reprocessamento completo na etapa escolhida")
    parser.add_argument("--msg", type=str, default="Atualizacao do catalogo inteligente CompraRibeirao", help="Mensagem de commit para o deploy")
    args = parser.parse_args()

    if args.step == "status":
        print_status_report()
    elif args.step == "discover":
        asyncio.run(run_discovery_step(args.query, max_per_term=args.limit or 25))
    elif args.step == "crawl-text":
        asyncio.run(crawl_all_store_texts(limit=args.limit, force_recrawl=args.force))
    elif args.step == "scrap":
        asyncio.run(run_scraping_step())
    elif args.step == "enrich-ai":
        run_enrichment(limit=args.limit, force_reprocess=args.force)
    elif args.step == "build-kb":
        build_knowledge_base()
    elif args.step == "deploy":
        deploy_to_cloud(args.msg)
    elif args.step == "all":
        asyncio.run(run_full_pipeline(query=args.query, force_ai=args.force))
