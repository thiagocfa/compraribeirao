"""
Crawler de Conteúdo Textual e Institucional - CompraRibeirão
Visita todas as lojas cadastradas no banco local, extrai títulos, descrições, cabeçalhos,
seções sobre a empresa, marcas e serviços, e armazena permanentemente em 'store_web_content'.
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
import re
import os
import sys
import sqlite3
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_connection, db_transaction, RAW_DB_PATH

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

def init_content_table():
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

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    # Remove múltiplos espaços e quebras de linha consecutivas
    text = re.sub(r'[\r\n\t]+', ' ', raw)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

async def crawl_single_store(client: httpx.AsyncClient, store: dict, sem: asyncio.Semaphore):
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

            # Remove scripts, estilos e tags invisíveis
            for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer"]):
                tag.extract()

            # Título
            title_tag = soup.find("title")
            page_title = clean_text(title_tag.get_text()) if title_tag else ""

            # Meta description / OpenGraph
            meta_desc = ""
            desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}) or \
                       soup.find("meta", attrs={"property": re.compile(r"^og:description$", re.I)})
            if desc_tag and desc_tag.get("content"):
                meta_desc = clean_text(desc_tag["content"])

            # Cabeçalhos h1 e h2
            h1s = [clean_text(h.get_text()) for h in soup.find_all("h1") if h.get_text(strip=True)]
            h2s = [clean_text(h.get_text()) for h in soup.find_all("h2") if h.get_text(strip=True)]
            
            h1_text = " | ".join(h1s[:6])
            h2_text = " | ".join(h2s[:10])

            # Texto do corpo (parágrafos, itens de lista e divs descritivas)
            paragraphs = []
            for p in soup.find_all(["p", "li"]):
                txt = clean_text(p.get_text())
                if len(txt) > 25: # Ignora links de 1 palavra
                    paragraphs.append(txt)

            body_text = " ".join(paragraphs[:40]) # Pega os 40 primeiros parágrafos informativos
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
    print("=" * 60)
    print("   COMPRARIBEIRÃO - CRAWLER DE CONTEÚDO TEXTUAL BRUTO")
    print("=" * 60)
    
    init_content_table()

    # Busca lojas
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        if force_recrawl:
            c.execute("SELECT id, name, website FROM stores WHERE website IS NOT NULL AND website != ''")
        else:
            # Apenas as que ainda não têm captura realizada com sucesso
            c.execute("""
            SELECT s.id, s.name, s.website 
            FROM stores s
            LEFT JOIN store_web_content w ON s.id = w.store_id
            WHERE s.website IS NOT NULL AND s.website != '' AND (w.status IS NULL OR w.status != 'success')
            """)
        stores = [dict(r) for r in c.fetchall()]

    if limit:
        stores = stores[:limit]

    print(f"\n[*] Total de lojas a rastrear: {len(stores)}")
    if not stores:
        print("[✓] Todas as lojas já têm dados textuais capturados!")
        return

    sem = asyncio.Semaphore(12) # 12 conexões simultâneas
    success_count = 0
    fail_count = 0

    async with httpx.AsyncClient(headers=HEADERS, verify=False, timeout=12.0) as client:
        tasks = [crawl_single_store(client, store, sem) for store in stores]
        
        # Processa com barra de progresso em lotes
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
            print(f"[i] Progresso: {done}/{len(tasks)} lojas rastreadas ({success_count} sucessos, {fail_count} falhas/timeouts)")

    print(f"\n[✓] Rastreamento textual concluído com sucesso!")
    print(f"Total com texto capturado: {success_count} | Falhas: {fail_count}")

if __name__ == "__main__":
    asyncio.run(crawl_all_store_texts())
