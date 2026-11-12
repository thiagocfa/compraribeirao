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

CATEGORY_PRETTY = {
    "informatica": "Informática & Periféricos",
    "material-eletrico": "Material Elétrico",
    "categoria-material-eletrico": "Material Elétrico",
    "rede-e-internet": "Redes & Internet",
    "categoria-rede-e-internet": "Redes & Internet",
    "energia": "Energia & Fontes",
    "categoria-energia": "Energia & Fontes",
    "seguranca": "Segurança & CFTV",
    "celular": "Celulares & Smartphones",
    "categoria-games": "Games & Consoles",
    "assistencia": "Assistência & Ferramentas",
    "notebook": "Notebooks & Acessórios",
    "diversos": "Diversos & Variedades",
    "motor": "Peças de Motor",
    "freios": "Freios & Pastilhas",
    "suspensao": "Suspensão & Amortecedores",
    "suspensaodirecao": "Suspensão & Direção",
    "filtros": "Filtros de Óleo e Ar",
    "oleos-e-fluidos": "Óleos & Fluidos Automotivos",
    "oleosfluidos": "Óleos & Fluidos",
    "acessorios": "Acessórios Automotivos",
    "ferramentas-estetica": "Ferramentas & Estética Automotiva",
    "iluminacao": "Iluminação & Faróis"
}

async def fetch_tray_sitemap_urls(client: httpx.AsyncClient, sitemap_url: str) -> list[str]:
    resp = await client.get(sitemap_url)
    if resp.status_code != 200:
        return []
    
    xml = resp.text
    sub_sitemaps = re.findall(r'<loc>(https?://[^<]+sitemap[^<]*\.xml)</loc>', xml)
    if sub_sitemaps:
        all_urls = []
        for sub in sub_sitemaps:
            try:
                sub_resp = await client.get(sub)
                if sub_resp.status_code == 200:
                    urls = re.findall(r'<loc>(https?://[^<]+)</loc>', sub_resp.text)
                    all_urls.extend(urls)
            except Exception:
                pass
        return all_urls
    
    return re.findall(r'<loc>(https?://[^<]+)</loc>', xml)

async def parse_tray_product(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str, dept_slug: str):
    async with sem:
        try:
            resp = await client.get(url, timeout=12.0)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, 'html.parser')
            cat_name = CATEGORY_PRETTY.get(dept_slug, dept_slug.replace('-', ' ').title())

            # 1. Tenta JSON-LD
            scripts = soup.find_all('script', type='application/ld+json')
            for s in scripts:
                if not s.string:
                    continue
                try:
                    data = json.loads(s.string)
                    if isinstance(data, dict) and data.get('@type') == 'Product':
                        name = data.get('name')
                        offers = data.get('offers', {})
                        price = 0.0
                        if isinstance(offers, dict):
                            price = float(offers.get('price', 0.0))
                        elif isinstance(offers, list) and offers:
                            price = float(offers[0].get('price', 0.0))
                        
                        image = data.get('image', '')
                        if isinstance(image, list) and image:
                            image = image[0]

                        brand = data.get('brand', '')
                        if isinstance(brand, dict):
                            brand = brand.get('name', '')

                        sku = data.get('sku', '') or data.get('productID', '')
                        desc = data.get('description', '') or ''

                        return {
                            "title": name,
                            "price": price,
                            "image_url": image,
                            "brand": brand,
                            "category": cat_name,
                            "sku": str(sku),
                            "description": desc[:1000],
                            "product_url": url
                        }
                except Exception:
                    pass

            # 2. Fallback: Seletores OpenGraph e HTML da Tray
            og_title = soup.find('meta', property='og:title')
            title = og_title['content'].split(' - RAICROM')[0].strip() if og_title else ''
            if not title:
                h1 = soup.find('h1')
                title = h1.get_text(strip=True) if h1 else ''

            if not title:
                return None

            og_image = soup.find('meta', property='og:image')
            image_url = og_image['content'] if og_image else ''

            price = 0.0
            preco_el = soup.find(class_='preco-avista') or soup.find(class_='PrecoPrincipal') or soup.find(class_=re.compile(r'preco|price', re.I))
            if preco_el:
                preco_txt = preco_el.get_text()
                match = re.search(r'R\$\s*([\d\.,]+)', preco_txt)
                if match:
                    raw_val = match.group(1).replace('.', '').replace(',', '.')
                    try:
                        price = float(raw_val)
                    except ValueError:
                        price = 0.0

            brand_el = soup.find(class_='brand')
            brand = brand_el.get_text(strip=True) if brand_el else 'Raicrom'

            sku_el = soup.find(class_='dados-valor')
            sku = sku_el.get_text(strip=True) if sku_el else ''

            return {
                "title": title,
                "price": price,
                "image_url": image_url,
                "brand": brand,
                "category": cat_name,
                "sku": sku,
                "description": title,
                "product_url": url
            }

        except Exception:
            return None
    return None

async def crawl_tray_full(store_id: str, sitemap_url: str):
    print(f"[*] Iniciando extração 100% COMPLETA para '{store_id}'...")
    conn = get_connection()
    cursor = conn.cursor()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12.0) as client:
        all_urls = await fetch_tray_sitemap_urls(client, sitemap_url)
        print(f"[i] Total de URLs no sitemap da {store_id}: {len(all_urls)}")

        # Filtra páginas institucionais / não-produtos
        product_tasks_info = []
        for u in all_urls:
            if any(skip in u for skip in ['/contato', '/login', '/carrinho', '/institucional', '/quem-somos', '/duvidas', '.xml']):
                continue
            
            parts = [p for p in u.replace("https://", "").replace("http://", "").split("/")[1:] if p]
            dept = parts[0] if len(parts) >= 2 else "geral"
            product_tasks_info.append((u, dept))

        total_items = len(product_tasks_info)
        print(f"[!] Coletando catálogo INTEGRAL: {total_items} produtos da loja {store_id} (SEM LIMITES)...")

        # Concorrência rápida de 25 requisições paralelas
        sem = asyncio.Semaphore(25)
        
        # Processa em lotes de 200 produtos para salvar e liberar memória
        batch_size = 200
        saved_total = 0
        t0 = time.time()

        for i in range(0, total_items, batch_size):
            batch = product_tasks_info[i:i + batch_size]
            tasks = [parse_tray_product(client, sem, u, dept) for u, dept in batch]
            results = await asyncio.gather(*tasks)

            for r in results:
                if not r or not r.get("title"):
                    continue
                
                p_id = f"{store_id}_{abs(hash(r['product_url']))}"
                cursor.execute("""
                INSERT INTO products (
                    id, store_id, sku, title, description, price, original_price,
                    category, brand, image_url, product_url, in_stock, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'crawler_tray')
                ON CONFLICT(id) DO UPDATE SET
                    price = excluded.price,
                    image_url = excluded.image_url,
                    title = excluded.title,
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                """, (
                    p_id, store_id, r["sku"], r["title"], r["description"],
                    r["price"], r["price"], r["category"], r["brand"], r["image_url"], r["product_url"]
                ))
                saved_total += 1

            conn.commit()
            elapsed = time.time() - t0
            pct = (min(i + batch_size, total_items) / total_items) * 100
            print(f"[+] {min(i + batch_size, total_items)}/{total_items} produtos ({pct:.1f}%) processados em {elapsed:.1f}s...")

        conn.close()
        print(f"[✓] FINALIZADO {store_id}: Total de {saved_total} produtos catalogados com sucesso!")

if __name__ == "__main__":
    async def run_all():
        # Raicrom: 100% dos 2.736 produtos
        await crawl_tray_full("raicrom", "https://www.raicrom.com.br/sitemap.xml")
        # Dorival: 100% dos 1.169 produtos
        await crawl_tray_full("dorival-autopecas", "https://www.dorivalautopecas.com.br/sitemap.xml")

    asyncio.run(run_all())
