import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from backend.search_terms import list_search_terms
from backend.discovery_gmaps import scrape_google_maps_stores
from backend.crawlers.universal_crawler import ingest_all_discovered_with_websites
from backend.indexer import rebuild_index

async def run_discovery_step(query: str = None, max_per_term: int = 25):
    if query:
        print(f"\n========================================================")
        print(f" ETAPA 1: Buscando lojas para '{query}' no Google Maps...")
        print(f"========================================================")
        await scrape_google_maps_stores(query, max_results=max_per_term)
    else:
        terms = list_search_terms()
        active_terms = [t for t in terms if t.get("active")]
        print(f"\n========================================================")
        print(f" ETAPA 1: Varrendo {len(active_terms)} setores comerciais de Ribeirão...")
        print(f"========================================================")
        for t in active_terms:
            term_text = t["term"]
            print(f"\n[>] Setor: {t['category']} ('{term_text}')...")
            await scrape_google_maps_stores(term_text, max_results=max_per_term)

async def run_scraping_step():
    print(f"\n========================================================")
    print(f" ETAPA 2: Extraindo produtos de todos os sites descobertos...")
    print(f"========================================================")
    await ingest_all_discovered_with_websites()

async def run_full_pipeline(query: str = None):
    # 1. Descoberta de Lojas
    await run_discovery_step(query)
    
    # 2. Scrap dos Produtos
    await run_scraping_step()

    # 3. Reindexação da busca
    rebuild_index()
    print("\n[✓] Pipeline completo finalizado com sucesso!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline CompraRibeirão")
    parser.add_argument("--step", choices=["discover", "scrap", "all"], default="all", help="Qual etapa rodar")
    parser.add_argument("--query", type=str, default=None, help="Termo específico para buscar (ex: 'pet shop')")
    parser.add_argument("--limit", type=int, default=25, help="Máximo de lojas por termo")
    args = parser.parse_args()

    if args.step == "discover":
        asyncio.run(run_discovery_step(args.query, args.limit))
    elif args.step == "scrap":
        asyncio.run(run_scraping_step())
    elif args.step == "all":
        asyncio.run(run_full_pipeline(args.query))
