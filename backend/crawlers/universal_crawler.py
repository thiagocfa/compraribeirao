import httpx
import re
import json
import asyncio
from bs4 import BeautifulSoup
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_connection
from crawlers.vtex_crawler import crawl_vtex_all
from crawlers.tray_crawler import crawl_tray_full

def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text.lower())
    return re.sub(r'[\s_-]+', '-', text).strip('-')

async def detect_ecommerce_platform(url: str, client: httpx.AsyncClient) -> str:
    try:
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        html = resp.text.lower()

        # 1. VTEX
        if "vtex" in html or "vteximg" in html:
            return "vtex"

        # 2. Tray
        if "tray" in html or "tcdn.com.br" in html or "/mvc/store/" in html:
            return "tray"

        # 3. Loja Integrada
        if "lojaintegrada" in html or "cdn.awsli.com.br" in html:
            return "loja_integrada"

        # 4. Shopify
        if "shopify" in html or "cdn.shopify.com" in html:
            return "shopify"

        # 5. Nuvemshop
        if "nuvemshop" in html or "mitiendanube" in html:
            return "nuvemshop"

        # 6. WooCommerce
        if "woocommerce" in html or "wp-content" in html:
            return "woocommerce"

        # Checa sitemaps conhecidos
        base = str(resp.url).rstrip('/')
        sitemap_resp = await client.get(f"{base}/sitemap.xml", timeout=6.0)
        if sitemap_resp.status_code == 200:
            s_text = sitemap_resp.text.lower()
            if "loja_integrada" in s_text or "product-1.xml" in s_text:
                return "loja_integrada"
            if "tray" in s_text or "sitemaps/sitemap_1.xml" in s_text:
                return "tray"
            if "vtex" in s_text:
                return "vtex"

        return "desconhecido"
    except Exception as e:
        return "inacessivel"

async def crawl_loja_integrada(store_id: str, base_url: str, max_products: int = 400):
    print(f"[*] Extraindo produtos Loja Integrada para '{store_id}' ({base_url})...")
    conn = get_connection()
    cursor = conn.cursor()
    base = base_url.rstrip('/')

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12.0) as client:
        # Pega sitemap de produtos
        sitemap_url = f"{base}/sitemap/product-1.xml"
        s_resp = await client.get(sitemap_url)
        if s_resp.status_code != 200:
            sitemap_url = f"{base}/sitemap.xml"
            s_resp = await client.get(sitemap_url)
        
        urls = re.findall(r'<loc>(https?://[^<]+)</loc>', s_resp.text)
        product_urls = [u for u in urls if not u.endswith('.xml') and len(u.split('/')) > 3][:max_products]
        print(f"[i] Extraindo dados de {len(product_urls)} produtos da Loja Integrada...")

        sem = asyncio.Semaphore(15)
        saved = 0

        async def parse_item(u):
            async with sem:
                try:
                    r = await client.get(u, timeout=10.0)
                    if r.status_code != 200:
                        return None
                    soup = BeautifulSoup(r.text, 'html.parser')
                    
                    og_title = soup.find('meta', property='og:title')
                    title = og_title['content'].strip() if og_title else ''
                    if not title:
                        h1 = soup.find('h1')
                        title = h1.get_text(strip=True) if h1 else ''
                    if not title:
                        return None

                    og_image = soup.find('meta', property='og:image')
                    image_url = og_image['content'] if og_image else ''

                    # Extrai preço
                    price = 0.0
                    m = re.findall(r'R\$\s*([\d\.,]+)', soup.get_text())
                    if m:
                        raw = m[0].replace('.', '').replace(',', '.')
                        try:
                            price = float(raw)
                        except ValueError:
                            price = 0.0

                    return {
                        "title": title,
                        "price": price,
                        "image_url": image_url,
                        "product_url": u
                    }
                except Exception:
                    return None

        results = await asyncio.gather(*[parse_item(u) for u in product_urls])
        for res in results:
            if not res or not res["title"]:
                continue
            
            p_id = f"{store_id}_{abs(hash(res['product_url']))}"
            cursor.execute("""
            INSERT INTO products (
                id, store_id, title, description, price, original_price,
                category, brand, image_url, product_url, in_stock, source_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'crawler_loja_integrada')
            ON CONFLICT(id) DO UPDATE SET
                price = excluded.price,
                image_url = excluded.image_url,
                title = excluded.title,
                updated_at = CURRENT_TIMESTAMP
            """, (
                p_id, store_id, res["title"], res["title"], res["price"], res["price"],
                "Música & Instrumentos", store_id, res["image_url"], res["product_url"]
            ))
            saved += 1

        conn.commit()
        conn.close()
        print(f"[✓] Concluído Loja Integrada ({store_id}): {saved} produtos catalogados!")
        return saved

async def process_and_ingest_store(store_data: dict):
    name = store_data.get("name")
    website = store_data.get("website")
    neighborhood = store_data.get("neighborhood") or "Ribeirão Preto"
    address = store_data.get("address") or "Ribeirão Preto - SP"
    phone = store_data.get("phone") or ""
    category = store_data.get("category") or "Geral"

    if not website or not website.startswith("http"):
        print(f"[-] Loja '{name}' não possui site com e-commerce cadastrado.")
        return 0

    slug = slugify(name)
    store_id = slug

    # Registra loja na tabela oficial 'stores'
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO stores (id, name, slug, category, neighborhood, address, city, state, whatsapp, website, platform)
    VALUES (?, ?, ?, ?, ?, ?, 'Ribeirão Preto', 'SP', ?, ?, 'universal')
    ON CONFLICT(id) DO UPDATE SET
        neighborhood = excluded.neighborhood,
        address = excluded.address,
        whatsapp = excluded.whatsapp,
        website = excluded.website
    """, (store_id, name, slug, category, neighborhood, address, phone.replace('(', '').replace(')', '').replace('-', '').replace(' ', ''), website))
    conn.commit()
    conn.close()

    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
        platform = await detect_ecommerce_platform(website, client)
        print(f"[i] Loja '{name}': Plataforma detectada = '{platform}'")

    saved_count = 0
    if platform == "tray":
        sitemap = website.rstrip('/') + "/sitemap.xml"
        await crawl_tray_full(store_id, sitemap)
        saved_count = 1
    elif platform == "vtex":
        await crawl_vtex_all(store_id, website)
        saved_count = 1
    elif platform == "loja_integrada":
        saved_count = await crawl_loja_integrada(store_id, website)
    else:
        # Se for plataforma desconhecida mas tiver sitemap padrão
        print(f"[i] Loja '{name}' usa plataforma '{platform}'. Tentando ingestão via sitemap universal...")
        try:
            saved_count = await crawl_loja_integrada(store_id, website, max_products=100)
        except Exception:
            pass

    # Marca loja como importada
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE discovered_stores SET status = 'imported', platform = ? WHERE name = ?", (platform, name))
    conn.commit()
    conn.close()

    return saved_count

async def ingest_all_discovered_with_websites():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM discovered_stores WHERE website IS NOT NULL AND website != '' AND status != 'imported'")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    print(f"\n[*] Encontradas {len(rows)} lojas descobertas com websites para processar...")
    total_new_products = 0

    for store in rows:
        print(f"\n---> Processando loja: {store['name']} ({store['website']})...")
        try:
            count = await process_and_ingest_store(store)
            total_new_products += count
        except Exception as e:
            print(f"[!] Erro ao processar loja {store['name']}: {e}")

    # Reindexa busca FTS5
    if total_new_products > 0:
        import indexer
        indexer.rebuild_index()

    print(f"\n[✓] Ingestão concluída com sucesso! Total de novas fontes integradas.")

if __name__ == "__main__":
    asyncio.run(ingest_all_discovered_with_websites())
