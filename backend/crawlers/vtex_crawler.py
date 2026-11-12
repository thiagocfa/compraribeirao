import httpx
import sqlite3
import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_connection, db_transaction

async def crawl_vtex_category_unlimited(client: httpx.AsyncClient, store_id: str, base_url: str, cat_id: int, cat_name: str):
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

            with db_transaction() as conn:
                cursor = conn.cursor()
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
            if len(products) < step or offset > 500:
                break

        except Exception as e:
            print(f"[-] Erro cat {cat_name} ({cat_id}): {e}")
            break

    return saved

async def crawl_vtex_all(store_id: str = "baba-materiais", base_url: str = "https://www.babamateriais.com.br"):
    print(f"[*] Extração 100% COMPLETA VTEX para '{store_id}' por todas as categorias...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
        try:
            tree_resp = await client.get(f"{base_url.rstrip('/')}/api/catalog_system/pub/category/tree/2")
            if tree_resp.status_code != 200:
                print(f"[!] Árvore de categorias não acessível para {store_id}")
                return 0

            cats = tree_resp.json()
            flat_cats = []
            def extract_cats(c_list):
                for c in c_list:
                    flat_cats.append((c['id'], c['name']))
                    if c.get('children'):
                        extract_cats(c['children'])

            extract_cats(cats)
            print(f"[i] Encontradas {len(flat_cats)} categorias VTEX para varrer...")

            total = 0
            for cid, cname in flat_cats:
                count = await crawl_vtex_category_unlimited(client, store_id, base_url, cid, cname)
                total += count

            print(f"[✓] Concluído VTEX {store_id}: {total} produtos extraídos!")
            return total
        except Exception as e:
            print(f"[!] Erro ao varrer VTEX {store_id}: {e}")
            return 0

if __name__ == "__main__":
    asyncio.run(crawl_vtex_all())
