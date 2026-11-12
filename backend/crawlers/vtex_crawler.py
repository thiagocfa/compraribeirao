import httpx
import sqlite3
import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_connection

async def crawl_vtex_category_unlimited(client: httpx.AsyncClient, cursor, store_id: str, base_url: str, cat_id: int, cat_name: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    saved = 0
    step = 50
    offset = 0

    while True:
        to_idx = offset + step - 1
        api_url = f"{base_url.rstrip('/')}/api/catalog_system/pub/products/search?fq=C:{cat_id}&_from={offset}&_to={to_idx}"
        try:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code not in (200, 206):
                break
            
            products = resp.json()
            if not products:
                break

            for p in products:
                product_id = f"{store_id}_{p.get('productId')}"
                title = p.get("productName")
                brand = p.get("brand")
                categories = p.get("categories", [])
                category = categories[0].strip("/").replace("/", " > ") if categories else cat_name
                product_url = p.get("link")
                description = p.get("description", "") or ""

                items = p.get("items", [])
                price = 0.0
                original_price = 0.0
                image_url = ""
                in_stock = True

                if items:
                    first_item = items[0]
                    images = first_item.get("images", [])
                    if images:
                        image_url = images[0].get("imageUrl", "")
                    
                    sellers = first_item.get("sellers", [])
                    if sellers:
                        offer = sellers[0].get("commertialOffer", {})
                        price = float(offer.get("Price", 0.0))
                        original_price = float(offer.get("ListPrice", price))
                        available_qty = offer.get("AvailableQuantity", 0)
                        in_stock = available_qty > 0

                cursor.execute("""
                INSERT INTO products (
                    id, store_id, sku, title, description, price, original_price,
                    category, brand, image_url, product_url, in_stock, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'crawler_vtex')
                ON CONFLICT(id) DO UPDATE SET
                    price = excluded.price,
                    original_price = excluded.original_price,
                    in_stock = excluded.in_stock,
                    image_url = excluded.image_url,
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                """, (
                    product_id, store_id, str(p.get("productId")), title, description[:1000],
                    price, original_price, category, brand, image_url, product_url, 1 if in_stock else 0
                ))
                saved += 1

            offset += step
            if len(products) < step or offset > 500: # Limite de segurança por categoria
                break

        except Exception as e:
            print(f"[-] Erro cat {cat_name} ({cat_id}): {e}")
            break

    return saved

async def crawl_vtex_all(store_id: str = "baba-materiais", base_url: str = "https://www.babamateriais.com.br"):
    print(f"[*] Extração 100% COMPLETA VTEX para '{store_id}' por todas as categorias...")
    conn = get_connection()
    cursor = conn.cursor()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
        try:
            tree_resp = await client.get(f"{base_url.rstrip('/')}/api/catalog_system/pub/category/tree/2")
            categories = tree_resp.json()
        except Exception as e:
            print(f"[!] Erro ao carregar departamentos da VTEX: {e}")
            categories = []

        total_saved = 0
        for cat in categories:
            cat_id = cat.get("id")
            cat_name = cat.get("name")
            print(f"[i] Coletando departamento completo: {cat_name} (ID: {cat_id})...")
            saved = await crawl_vtex_category_unlimited(client, cursor, store_id, base_url, cat_id, cat_name)
            total_saved += saved
            conn.commit()
            print(f"    -> {saved} produtos catalogados em {cat_name}")

    conn.close()
    print(f"[✓] Concluído Babá Materiais: Total de {total_saved} produtos inseridos/atualizados!")

if __name__ == "__main__":
    asyncio.run(crawl_vtex_all())
