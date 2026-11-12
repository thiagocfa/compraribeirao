import asyncio
import urllib.parse
import re
from playwright.async_api import async_playwright
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_connection

def init_discovery_table():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS discovered_stores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        neighborhood TEXT,
        address TEXT,
        phone TEXT,
        website TEXT,
        rating REAL,
        reviews_count INTEGER,
        maps_url TEXT,
        platform TEXT, -- 'tray', 'vtex', 'nuvemshop', 'woocommerce', 'institucional', 'desconhecido'
        has_ecommerce BOOLEAN DEFAULT 0,
        status TEXT DEFAULT 'pending', -- 'pending', 'imported', 'ignored'
        query_used TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, address)
    )
    """)
    conn.commit()
    conn.close()

def parse_neighborhood(address: str) -> str:
    # Ex: R. Bernardino de Campos, 1617 - Centro, Ribeirão Preto - SP, 14015-130
    if not address:
        return "Ribeirão Preto"
    match = re.search(r'-\s*([^,]+),\s*Ribeir[ãa]o Preto', address, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Ribeirão Preto"

async def scrape_google_maps_stores(search_query: str, max_results: int = 15):
    print(f"\n[*] Iniciando robô Google Maps (CUSTO ZERO) para busca: '{search_query}'...")
    init_discovery_table()
    
    # Adiciona "ribeirão preto" à busca caso o usuário não tenha colocado
    if "ribeir" not in search_query.lower():
        full_query = f"{search_query} ribeirao preto"
    else:
        full_query = search_query

    url = "https://www.google.com/maps/search/" + urllib.parse.quote(full_query)

    discovered = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="pt-BR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(3)

            # Fecha modal de cookies/consentimento se aparecer
            for btn_txt in ["Aceitar tudo", "Concordo", "I agree", "Aceito"]:
                try:
                    btn = page.locator(f"button:has-text('{btn_txt}')")
                    if await btn.count() > 0:
                        await btn.first.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass

            # Rola a lista de resultados para carregar mais lojas
            feed = page.locator("div[role='feed']")
            if await feed.count() > 0:
                for _ in range(4):
                    await feed.evaluate("el => el.scrollBy(0, 1500)")
                    await asyncio.sleep(1.2)

            # Localiza os itens de lojas
            items = page.locator("div.Nv2PK")
            total_items = await items.count()
            print(f"[+] Total de estabelecimentos avistados no Maps: {total_items}")

            limit = min(total_items, max_results)
            print(f"[i] Coletando detalhes de {limit} lojas em tempo real...")
            
            for i in range(limit):
                try:
                    item = items.nth(i)
                    
                    # Nome e categoria básica do card
                    text = await item.inner_text(timeout=2000)
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    name = lines[0] if lines else f"Loja {i+1}"
                    
                    print(f"  [{i+1}/{limit}] Lendo: {name[:35]}...", end="\r", flush=True)

                    # Clica no card para abrir o painel lateral com timeout de 2.5s
                    card_link = item.locator("a[href*='/maps/place/']").first
                    maps_url = ""
                    website = ""
                    phone = ""
                    address = ""

                    if await card_link.count() > 0:
                        try:
                            maps_url = await card_link.get_attribute("href", timeout=2000) or ""
                            await card_link.click(timeout=2500)
                            await asyncio.sleep(0.8)
                            
                            # Tenta ler website e telefone do painel lateral
                            authority_btn = page.locator("a[data-item-id='authority'], a[aria-label*='website'], a[aria-label*='Website']")
                            phone_btn = page.locator("button[data-item-id*='phone']")
                            address_btn = page.locator("button[data-item-id='address']")
                            
                            if await authority_btn.count() > 0:
                                website = await authority_btn.first.get_attribute("href", timeout=1500) or ""
                            if await phone_btn.count() > 0:
                                p_raw = await phone_btn.first.inner_text(timeout=1500) or ""
                                phone = re.sub(r'[^\d\(\)\-\s\+]', '', p_raw).strip()
                            if await address_btn.count() > 0:
                                a_raw = await address_btn.first.inner_text(timeout=1500) or ""
                                address = a_raw.replace("", "").strip()
                        except Exception:
                            pass

                    # Fallback de endereço a partir das linhas do card
                    if not address and len(lines) > 2:
                        address = lines[2]
                    neighborhood = parse_neighborhood(address)

                    store_data = {
                        "name": name,
                        "category": search_query,
                        "neighborhood": neighborhood,
                        "address": address or "Ribeirão Preto - SP",
                        "phone": phone,
                        "website": website,
                        "rating": 0.0,
                        "reviews_count": 0,
                        "maps_url": maps_url,
                        "query_used": search_query
                    }

                    # Salva no banco de dados SQLite com timeout seguro
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("""
                    INSERT INTO discovered_stores (
                        name, category, neighborhood, address, phone, website,
                        rating, reviews_count, maps_url, query_used
                    ) VALUES (
                        :name, :category, :neighborhood, :address, :phone, :website,
                        :rating, :reviews_count, :maps_url, :query_used
                    )
                    ON CONFLICT(name, address) DO UPDATE SET
                        website = CASE WHEN excluded.website != '' THEN excluded.website ELSE discovered_stores.website END,
                        phone = CASE WHEN excluded.phone != '' THEN excluded.phone ELSE discovered_stores.phone END
                    """, store_data)
                    conn.commit()
                    conn.close()

                    discovered.append(store_data)
                    print(f"  [{i+1}/{limit}] {name[:30]} ({neighborhood[:15]}) | Tel: {phone or 'N/A'} | Site: {website or 'Sem site'}")

                except Exception as ex:
                    continue

        except Exception as e:
            print(f"[!] Erro ao navegar no Google Maps: {e}")

        await browser.close()

    print(f"\n[✓] Sucesso: {len(discovered)} lojas de Ribeirão Preto descobertas e salvas sem custo!")
    return discovered

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "instrumentos musicais ribeirao preto"
    asyncio.run(scrape_google_maps_stores(query, max_results=10))
