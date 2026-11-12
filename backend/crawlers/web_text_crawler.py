r"""
================================================================================
EXTRATOR DE CONTEÚDO TEXTUAL DOS SITES (backend/crawlers/web_text_crawler.py)
================================================================================
Objetivo:
  Garantir que TODAS as lojas físicas de Ribeirão Preto que possuem website
  tenham seu conteúdo textual salvo no banco local ('compraribeirao.db' -> tabela
  'store_web_content'), independentemente de terem e-commerce de produtos ou serem
  apenas sites institucionais/landing pages.

O que este módulo faz passo a passo:
  1. Sincroniza automaticamente novas lojas da tabela 'discovered_stores' (Google Maps)
     para a tabela mestre 'stores' (função sync_discovered_to_stores).
  2. Visita cada website de forma assíncrona (12 conexões simultâneas).
  3. Extrai:
     - Título da página (<title>)
     - Meta Description / OpenGraph Description
     - Cabeçalhos principais (<h1> e <h2>)
     - Parágrafos e listas descritivas do corpo da página (<p>, <li>)
  4. Salva permanentemente em 'store_web_content' para que a IA local (Qwen 2.5)
     possa interpretar com o que a empresa trabalha, marcas e especialidades.

Como executar via terminal:
  - Extrair texto apenas das lojas novas/pendentes:
      .\venv\Scripts\python backend/crawlers/web_text_crawler.py
  - Forçar nova leitura de todos os sites (--force):
      .\venv\Scripts\python backend/crawlers/web_text_crawler.py --force
================================================================================
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
import re
import os
import sys
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db_transaction, RAW_DB_PATH

# Cabeçalhos HTTP simulando navegador real em Português para evitar bloqueios
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def slugify(text: str) -> str:
    """Converte o nome da loja em um identificador único limpo (ex: 'Casa das Tintas' -> 'casa-das-tintas')."""
    text = re.sub(r'[^\w\s-]', '', text.lower())
    return re.sub(r'[\s_-]+', '-', text).strip('-')


def init_content_table():
    """Cria a tabela 'store_web_content' no banco bruto local caso ainda não exista."""
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS store_web_content (
            store_id TEXT PRIMARY KEY,
            store_name TEXT,
            website TEXT NOT NULL,
            page_title TEXT,
            meta_description TEXT,
            h1_headings TEXT,
            h2_headings TEXT,
            body_text TEXT,
            raw_html_length INTEGER,
            status TEXT DEFAULT 'pending', -- 'success', 'failed', 'timeout'
            error_msg TEXT,
            crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)


def sync_discovered_to_stores() -> int:
    """
    Garante que toda loja descoberta no Google Maps ('discovered_stores') seja
    promovida para a tabela principal 'stores' antes de rodar o extrator de textos.
    Retorna a quantidade de lojas sincronizadas.
    """
    synced = 0
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        # Verifica se a tabela discovered_stores existe
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='discovered_stores'")
        if not c.fetchone():
            return 0

        c.execute("SELECT * FROM discovered_stores")
        discovered_rows = [dict(r) for r in c.fetchall()]

        for d in discovered_rows:
            name = (d.get("name") or "").strip()
            if not name:
                continue
            slug = slugify(name)
            if not slug:
                continue
            phone_clean = re.sub(r'[^\d]', '', d.get("phone") or "")
            c.execute("""
            INSERT INTO stores (id, name, slug, category, neighborhood, address, city, state, whatsapp, website, platform)
            VALUES (?, ?, ?, ?, ?, ?, 'Ribeirão Preto', 'SP', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                website = CASE WHEN excluded.website != '' AND (stores.website IS NULL OR stores.website = '') THEN excluded.website ELSE stores.website END,
                whatsapp = CASE WHEN excluded.whatsapp != '' AND (stores.whatsapp IS NULL OR stores.whatsapp = '') THEN excluded.whatsapp ELSE stores.whatsapp END,
                address = CASE WHEN excluded.address != '' AND (stores.address IS NULL OR stores.address = '') THEN excluded.address ELSE stores.address END
            """, (
                slug,
                name,
                slug,
                d.get("category") or "Comércio Local",
                d.get("neighborhood") or "Ribeirão Preto",
                d.get("address") or "Ribeirão Preto - SP",
                phone_clean,
                d.get("website") or "",
                d.get("platform") or "institucional"
            ))
            synced += 1
    return synced


def clean_text(raw: str) -> str:
    """Remove quebras de linha e espaços múltiplos de textos extraídos do HTML."""
    if not raw:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', raw)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


async def crawl_single_store(client: httpx.AsyncClient, store: dict, sem: asyncio.Semaphore):
    """
    Visita o site de uma única loja, limpa o HTML e extrai os campos textuais relevantes.
    """
    store_id = store["id"]
    name = store["name"]
    website = store["website"]

    if not website or not website.startswith("http"):
        return {"store_id": store_id, "status": "failed", "error": "URL inválida"}

    async with sem:
        try:
            resp = await client.get(website, timeout=12.0, follow_redirects=True)
            if resp.status_code >= 400:
                return {
                    "store_id": store_id,
                    "store_name": name,
                    "website": website,
                    "status": "failed",
                    "error": f"HTTP {resp.status_code}"
                }

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Remove tags de código, estilo e rodapés repetitivos que não agregam semântica
            for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer"]):
                tag.extract()

            # 1. Título da Página (<title>)
            title_tag = soup.find("title")
            page_title = clean_text(title_tag.get_text()) if title_tag else ""

            # 2. Meta Description ou OpenGraph Description
            meta_desc = ""
            desc_tag = (
                soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
                or soup.find("meta", attrs={"property": re.compile(r"^og:description$", re.I)})
            )
            if desc_tag and desc_tag.get("content"):
                meta_desc = clean_text(desc_tag["content"])

            # 3. Cabeçalhos H1 e H2 (onde geralmente ficam os serviços e categorias da empresa)
            h1s = [clean_text(h.get_text()) for h in soup.find_all("h1") if h.get_text(strip=True)]
            h2s = [clean_text(h.get_text()) for h in soup.find_all("h2") if h.get_text(strip=True)]

            h1_text = " | ".join(h1s[:6])
            h2_text = " | ".join(h2s[:10])

            # 4. Parágrafos e Itens de Lista do Corpo (<p>, <li>)
            paragraphs = []
            for p in soup.find_all(["p", "li"]):
                txt = clean_text(p.get_text())
                if len(txt) > 25:  # Ignora menus curtos de 1 ou 2 palavras
                    paragraphs.append(txt)

            body_text = " ".join(paragraphs[:40])
            if len(body_text) > 4000:
                body_text = body_text[:4000]

            return {
                "store_id": store_id,
                "store_name": name,
                "website": website,
                "page_title": page_title[:250],
                "meta_description": meta_desc[:500],
                "h1_headings": h1_text[:500],
                "h2_headings": h2_text[:800],
                "body_text": body_text,
                "raw_html_length": len(html),
                "status": "success",
                "error": ""
            }

        except httpx.TimeoutException:
            return {
                "store_id": store_id,
                "store_name": name,
                "website": website,
                "status": "timeout",
                "error": "Timeout ao conectar"
            }
        except Exception as e:
            return {
                "store_id": store_id,
                "store_name": name,
                "website": website,
                "status": "failed",
                "error": str(e)[:150]
            }


async def crawl_all_store_texts(limit: int = None, force_recrawl: bool = False):
    """
    Executa a captura textual em lote para todas as lojas com website cadastrado.
    """
    print("=" * 64)
    print("   COMPRARIBEIRÃO - EXTRATOR DE CONTEÚDO TEXTUAL DOS SITES")
    print("=" * 64)

    init_content_table()
    sync_discovered_to_stores()

    # Seleciona as lojas no banco bruto local
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        if force_recrawl:
            c.execute("SELECT id, name, website FROM stores WHERE website IS NOT NULL AND website != ''")
        else:
            c.execute("""
            SELECT s.id, s.name, s.website 
            FROM stores s
            LEFT JOIN store_web_content w ON s.id = w.store_id
            WHERE s.website IS NOT NULL AND s.website != '' AND (w.status IS NULL OR w.status != 'success')
            """)
        stores = [dict(r) for r in c.fetchall()]

    if limit:
        stores = stores[:limit]

    print(f"\n[*] Total de sites na fila para extração textual: {len(stores)}")
    if not stores:
        print("[✓] Todas as lojas com site já estão com conteúdo textual salvo! (Use --force para recapturar)")
        return 0

    sem = asyncio.Semaphore(12)  # Até 12 sites visitados em paralelo
    success_count = 0
    fail_count = 0

    async with httpx.AsyncClient(headers=HEADERS, verify=False, timeout=12.0) as client:
        tasks = [crawl_single_store(client, store, sem) for store in stores]

        # Grava em lotes de 25 lojas para manter o progresso seguro no SQLite
        batch_size = 25
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            results = await asyncio.gather(*batch)

            with db_transaction(RAW_DB_PATH) as conn:
                c = conn.cursor()
                for res in results:
                    c.execute("""
                    INSERT INTO store_web_content (
                        store_id, store_name, website, page_title, meta_description,
                        h1_headings, h2_headings, body_text, raw_html_length, status, error_msg, crawled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(store_id) DO UPDATE SET
                        page_title = excluded.page_title,
                        meta_description = excluded.meta_description,
                        h1_headings = excluded.h1_headings,
                        h2_headings = excluded.h2_headings,
                        body_text = excluded.body_text,
                        raw_html_length = excluded.raw_html_length,
                        status = excluded.status,
                        error_msg = excluded.error_msg,
                        crawled_at = CURRENT_TIMESTAMP
                    """, (
                        res["store_id"], res.get("store_name", ""), res.get("website", ""),
                        res.get("page_title", ""), res.get("meta_description", ""),
                        res.get("h1_headings", ""), res.get("h2_headings", ""),
                        res.get("body_text", ""), res.get("raw_html_length", 0),
                        res["status"], res.get("error", "")
                    ))

                    if res["status"] == "success":
                        success_count += 1
                    else:
                        fail_count += 1

            done = min(i + batch_size, len(tasks))
            print(f"[i] Progresso: {done}/{len(tasks)} sites visitados ({success_count} com texto extraído, {fail_count} offline/falhas)", flush=True)

    print(f"\n[✓] Extração textual concluída! Sucessos: {success_count} | Falhas/Offline: {fail_count}")
    return success_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extrator de Conteúdo Textual dos Sites das Lojas")
    parser.add_argument("--limit", type=int, default=None, help="Limitar número de sites visitados")
    parser.add_argument("--force", action="store_true", help="Re-visitar todos os sites mesmo os já capturados")
    args = parser.parse_args()

    asyncio.run(crawl_all_store_texts(limit=args.limit, force_recrawl=args.force))
