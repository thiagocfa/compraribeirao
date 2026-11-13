r"""
================================================================================
EXTRATOR UNIVERSAL DE PRODUTOS E-COMMERCE (backend/crawlers/universal_crawler.py)
================================================================================
Objetivo:
  Detectar automaticamente a plataforma de e-commerce do site de cada loja física
  de Ribeirão Preto e extrair seus produtos (Título, Preço, Marca, Categoria,
  Foto e Link) para a tabela 'products' do banco bruto ('compraribeirao.db').

Plataformas Suportadas (v3.0):
  1. VTEX           : Via API pública de catálogo (vtex_crawler.py)
  2. Tray           : Via Sitemaps XML de produtos (tray_crawler.py)
  3. Shopify        : Via endpoint JSON nativo (/products.json?limit=250)
  4. WooCommerce    : Via API pública (/wp-json/wc/store/products) + Fallback Sitemap/JSON-LD
  5. Nuvemshop      : Via Sitemap XML + Extrator estruturado JSON-LD (Schema.org/Product)
  6. Loja Integrada : Via Sitemap (/sitemap/product-1.xml) + JSON-LD / OpenGraph
  7. Universal      : Qualquer site com Schema.org/Product (JSON-LD) ou OpenGraph de produto

Como executar via terminal:
  - Processar lojas novas descobertas no Google Maps:
      .\venv\Scripts\python backend/crawlers/universal_crawler.py
  - Re-escanear lojas WooCommerce, Shopify e Nuvemshop que ainda não têm produtos:
      .\venv\Scripts\python backend/crawlers/universal_crawler.py --backfill
================================================================================
"""

import httpx
import re
import json
import asyncio
from bs4 import BeautifulSoup
import sys
import os
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db_transaction, RAW_DB_PATH
from crawlers.vtex_crawler import crawl_vtex_all
from crawlers.tray_crawler import crawl_tray_full

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

SOCIAL_DOMAINS = ("instagram.com", "facebook.com", "linktr.ee", "wa.me", "whatsapp.com", "youtube.com", "tiktok.com")


def slugify(text: str) -> str:
    """Converte o nome da loja em um ID limpo."""
    text = re.sub(r'[^\w\s-]', '', text.lower())
    return re.sub(r'[\s_-]+', '-', text).strip('-')


def is_social_or_invalid_url(url: str) -> bool:
    """Ignora links de redes sociais que não são lojas virtuais."""
    if not url or not url.startswith("http"):
        return True
    u_low = url.lower()
    return any(d in u_low for d in SOCIAL_DOMAINS)


async def detect_ecommerce_platform(url: str, client: httpx.AsyncClient) -> str:
    """
    Inspeciona o HTML e cabeçalhos do site da loja para identificar a plataforma de e-commerce.
    """
    if is_social_or_invalid_url(url):
        return "rede_social"

    try:
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        final_url = str(resp.url).lower()
        if any(d in final_url for d in SOCIAL_DOMAINS):
            return "rede_social"

        html = resp.text.lower()

        # 1. VTEX
        if "vtexassets.com" in html or "vteximg.com.br" in html or "__vtex" in html:
            return "vtex"

        # 2. Tray Commerce
        if "tcdn.com.br" in html or "/mvc/store/" in html or "tray.com.br" in html:
            return "tray"

        # 3. Loja Integrada
        if "lojaintegrada.com.br" in html or "cdn.awsli.com.br" in html:
            return "loja_integrada"

        # 4. Shopify
        if "cdn.shopify.com" in html or "shopify.theme" in html:
            return "shopify"

        # 5. Nuvemshop / Tiendanube
        if "nuvemshop" in html or "mitiendanube" in html or "d26lpennugtm8s.cloudfront.net" in html:
            return "nuvemshop"

        # 6. WooCommerce (WordPress)
        if "woocommerce" in html or "wc-blocks" in html or "wp-content/plugins/woocommerce" in html:
            return "woocommerce"

        # 7. Verifica se o site possui marcação Schema.org Product na própria página ou sitemap
        if '"@type":"product"' in html.replace(" ", "") or 'property="product:price:amount"' in html:
            return "schema_product"

        return "institucional"
    except Exception:
        return "inacessivel"


def save_products_batch(store_id: str, items: list, source_type: str) -> int:
    """
    Salva uma lista de produtos extraídos na tabela 'products' do banco bruto local.
    """
    if not items:
        return 0

    saved = 0
    with db_transaction(RAW_DB_PATH) as conn:
        cursor = conn.cursor()
        for res in items:
            title = (res.get("title") or "").strip()
            if not title or len(title) < 3:
                continue
            p_url = res.get("product_url") or ""
            p_id = f"{store_id}_{abs(hash(p_url or title))}"
            price = float(res.get("price") or 0.0)
            brand = (res.get("brand") or "").strip() or store_id
            category = (res.get("category") or "Comércio Local").strip()
            image_url = (res.get("image_url") or "").strip()

            cursor.execute("""
            INSERT INTO products (
                id, store_id, title, description, price, original_price,
                category, brand, image_url, product_url, in_stock, source_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                price = CASE WHEN excluded.price > 0 THEN excluded.price ELSE products.price END,
                image_url = CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE products.image_url END,
                title = excluded.title,
                brand = excluded.brand,
                updated_at = CURRENT_TIMESTAMP
            """, (
                p_id, store_id, title[:220], title[:220], price, price,
                category[:100], brand[:80], image_url, p_url, source_type
            ))
            saved += 1
    return saved


async def crawl_shopify(store_id: str, base_url: str, max_products: int = 250) -> int:
    """
    Extrator Nativo Shopify: consome '/products.json?limit=250'.
    """
    print(f"[*] [Shopify] Extraindo produtos de '{store_id}' ({base_url})...")
    base = base_url.rstrip("/")
    api_url = f"{base}/products.json?limit={min(max_products, 250)}"

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15.0, verify=False) as client:
        try:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return await crawl_jsonld_universal(store_id, base_url, "crawler_shopify", max_products=120)

            data = resp.json()
            raw_products = data.get("products") or []
            extracted = []
            for p in raw_products:
                title = p.get("title") or ""
                handle = p.get("handle") or ""
                vendor = p.get("vendor") or ""
                p_type = p.get("product_type") or "Geral"
                images = p.get("images") or []
                img_src = images[0].get("src", "") if images else ""
                variants = p.get("variants") or []
                price = 0.0
                if variants:
                    try:
                        price = float(variants[0].get("price") or 0.0)
                    except Exception:
                        price = 0.0

                extracted.append({
                    "title": title,
                    "price": price,
                    "brand": vendor,
                    "category": p_type,
                    "image_url": img_src,
                    "product_url": f"{base}/products/{handle}" if handle else base
                })

            saved = save_products_batch(store_id, extracted, "crawler_shopify")
            print(f"[✓] [Shopify] {saved} produtos salvos para '{store_id}'.")
            return saved
        except Exception as e:
            print(f"[!] Aviso Shopify em {store_id}: {e}")
            return 0


async def crawl_woocommerce(store_id: str, base_url: str, max_products: int = 250) -> int:
    """
    Extrator Nativo WooCommerce (WordPress):
    1. Tenta a Store API pública (/wp-json/wc/store/products?per_page=100).
    2. Caso bloqueada ou desativada, usa o fallback de Sitemap XML (/product-sitemap.xml) + JSON-LD.
    """
    print(f"[*] [WooCommerce] Extraindo produtos de '{store_id}' ({base_url})...")
    base = base_url.rstrip("/")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15.0, verify=False) as client:
        extracted = []
        for page in range(1, 4):
            api_url = f"{base}/wp-json/wc/store/products?per_page=80&page={page}"
            try:
                resp = await client.get(api_url)
                if resp.status_code != 200 or not resp.text.strip().startswith("["):
                    break
                items = resp.json()
                if not isinstance(items, list) or not items:
                    break

                for it in items:
                    title = it.get("name") or ""
                    permalink = it.get("permalink") or base
                    images = it.get("images") or []
                    img_src = images[0].get("src", "") if images else ""
                    cats = it.get("categories") or []
                    cat_name = cats[0].get("name", "Geral") if cats else "Geral"

                    # Preço na Store API do WooCommerce vem em centavos ou com minor_unit
                    prices_obj = it.get("prices") or {}
                    raw_price = prices_obj.get("price") or "0"
                    minor_unit = int(prices_obj.get("currency_minor_unit", 2))
                    try:
                        price = float(raw_price) / (10 ** minor_unit)
                    except Exception:
                        price = 0.0

                    extracted.append({
                        "title": BeautifulSoup(title, "html.parser").get_text(strip=True),
                        "price": price,
                        "brand": "",
                        "category": cat_name,
                        "image_url": img_src,
                        "product_url": permalink
                    })
                if len(items) < 80 or len(extracted) >= max_products:
                    break
            except Exception:
                break

        if extracted:
            saved = save_products_batch(store_id, extracted[:max_products], "crawler_woocommerce")
            print(f"[✓] [WooCommerce API] {saved} produtos salvos para '{store_id}'.")
            return saved

    # Fallback: Sitemap de produtos do WooCommerce + JSON-LD / HTML
    return await crawl_jsonld_universal(store_id, base_url, "crawler_woocommerce", max_products=120)


def extract_product_from_html(html: str, url: str) -> dict:
    """
    Extrai dados estruturados de um produto a partir do HTML da página usando:
    1. Schema.org JSON-LD (@type: Product)
    2. Meta tags OpenGraph (og:title, og:image, product:price:amount)
    3. Classes comuns de preço (WooCommerce, Nuvemshop, Loja Integrada)
    """
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    price = 0.0
    image_url = ""
    brand = ""
    category = "Comércio Local"

    # 1. Tenta ler JSON-LD (<script type="application/ld+json">)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw_json = script.string or script.get_text()
            if not raw_json:
                continue
            data = json.loads(raw_json.strip())
            candidates = data if isinstance(data, list) else [data]
            for node in candidates:
                if not isinstance(node, dict):
                    continue
                # Suporte a @graph do Yoast SEO / RankMath no WooCommerce
                graph = node.get("@graph") if isinstance(node.get("@graph"), list) else [node]
                for item in graph:
                    if not isinstance(item, dict):
                        continue
                    t = str(item.get("@type") or "").lower()
                    if "product" in t:
                        title = title or (item.get("name") or "").strip()
                        img = item.get("image")
                        if isinstance(img, list) and img:
                            img = img[0]
                        if isinstance(img, dict):
                            img = img.get("url") or img.get("contentUrl") or ""
                        if isinstance(img, str):
                            image_url = image_url or img

                        b = item.get("brand")
                        if isinstance(b, dict):
                            brand = brand or (b.get("name") or "")
                        elif isinstance(b, str):
                            brand = brand or b

                        offers = item.get("offers")
                        if isinstance(offers, list) and offers:
                            offers = offers[0]
                        if isinstance(offers, dict):
                            p_val = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
                            if p_val:
                                try:
                                    price = float(str(p_val).replace(",", "."))
                                except ValueError:
                                    pass
        except Exception:
            continue

    # 2. Complementa com OpenGraph se faltar título, imagem ou preço
    if not title:
        og_t = soup.find("meta", property="og:title")
        if og_t and og_t.get("content"):
            title = og_t["content"].strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

    if not image_url:
        og_i = soup.find("meta", property="og:image")
        if og_i and og_i.get("content"):
            image_url = og_i["content"].strip()

    if price <= 0:
        og_p = (
            soup.find("meta", property="product:price:amount")
            or soup.find("meta", property="og:price:amount")
            or soup.find("meta", itemprop="price")
        )
        if og_p and og_p.get("content"):
            try:
                price = float(str(og_p["content"]).replace(".", "").replace(",", ".") if "," in str(og_p["content"]) else str(og_p["content"]))
            except ValueError:
                pass

    # 3. Fallback regex para R$ no corpo da página se ainda não achou preço
    if price <= 0:
        m = re.findall(r'R\$\s*([\d\.]{1,8},\d{2})', soup.get_text())
        if m:
            try:
                price = float(m[0].replace(".", "").replace(",", "."))
            except ValueError:
                price = 0.0

    if not title:
        return None

    return {
        "title": title,
        "price": price,
        "brand": brand,
        "category": category,
        "image_url": image_url,
        "product_url": url
    }


async def discover_product_urls_from_sitemap(client: httpx.AsyncClient, base_url: str, max_urls: int = 120) -> list:
    """
    Localiza URLs de produtos em sitemaps do WooCommerce, Nuvemshop, Loja Integrada ou genéricos.
    """
    base = base_url.rstrip("/")
    candidate_sitemaps = [
        f"{base}/product-sitemap.xml",
        f"{base}/product-sitemap1.xml",
        f"{base}/sitemap/product-1.xml",
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
    ]

    product_urls = []
    visited_sitemaps = set()

    for sm_url in candidate_sitemaps:
        if sm_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sm_url)
        try:
            r = await client.get(sm_url, timeout=8.0)
            if r.status_code != 200 or "<loc>" not in r.text:
                continue
            locs = re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", r.text)

            # Se for um índice de sitemaps, procura sub-sitemaps de produtos
            sub_sitemaps = [u for u in locs if u.endswith(".xml") or "sitemap" in u.lower()]
            direct_pages = [u for u in locs if not u.endswith(".xml") and "sitemap" not in u.lower()]

            for sub in sub_sitemaps:
                if any(k in sub.lower() for k in ("product", "produto", "loja", "shop", "sitemap_1", "product-1")):
                    if sub not in visited_sitemaps:
                        visited_sitemaps.add(sub)
                        try:
                            sr = await client.get(sub, timeout=8.0)
                            if sr.status_code == 200:
                                sub_locs = re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", sr.text)
                                direct_pages.extend([u for u in sub_locs if not u.endswith(".xml")])
                        except Exception:
                            pass

            # Filtra URLs que parecem páginas de produtos
            for u in direct_pages:
                u_low = u.lower()
                if any(skip in u_low for skip in ("/blog", "/contato", "/sobre", "/quem-somos", "/politica", "/termos", "/cart", "/checkout", "/minha-conta", "/wp-content/")):
                    continue
                if len(u.rstrip("/").split("/")) >= 4:
                    product_urls.append(u)
                if len(product_urls) >= max_urls:
                    break

            if len(product_urls) >= 15:
                break
        except Exception:
            continue

    return list(dict.fromkeys(product_urls))[:max_urls]


async def crawl_jsonld_universal(store_id: str, base_url: str, source_label: str = "crawler_universal", max_products: int = 120) -> int:
    """
    Extrator Universal baseado em Sitemap + JSON-LD (Schema.org/Product) e OpenGraph.
    Atende Nuvemshop, Loja Integrada, WooCommerce sem API e e-commerces próprios.
    """
    print(f"[*] [{source_label}] Buscando produtos em '{store_id}' ({base_url})...")
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=12.0, verify=False) as client:
        product_urls = await discover_product_urls_from_sitemap(client, base_url, max_urls=max_products)
        if not product_urls:
            print(f"[-] Nenhuma URL de produto localizada no sitemap de '{store_id}'.")
            return 0

        print(f"[i] Analisando {len(product_urls)} páginas de produtos de '{store_id}'...")
        sem = asyncio.Semaphore(14)

        async def fetch_one(u: str):
            async with sem:
                try:
                    r = await client.get(u, timeout=10.0)
                    if r.status_code != 200:
                        return None
                    return extract_product_from_html(r.text, u)
                except Exception:
                    return None

        results = await asyncio.gather(*[fetch_one(u) for u in product_urls])
        valid = [r for r in results if r and r.get("title") and (r.get("price", 0) > 0 or r.get("image_url"))]

        saved = save_products_batch(store_id, valid, source_label)
        print(f"[✓] [{source_label}] {saved} produtos extraídos para '{store_id}'!")
        return saved


async def process_and_ingest_store(store_data: dict) -> int:
    """
    Registra a loja na tabela 'stores', detecta sua plataforma e executa o extrator adequado.
    """
    name = store_data.get("name")
    website = store_data.get("website")
    neighborhood = store_data.get("neighborhood") or "Ribeirão Preto"
    address = store_data.get("address") or "Ribeirão Preto - SP"
    phone = store_data.get("phone") or ""
    category = store_data.get("category") or "Geral"

    if is_social_or_invalid_url(website):
        return 0

    slug = slugify(name)
    store_id = slug

    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        INSERT INTO stores (id, name, slug, category, neighborhood, address, city, state, whatsapp, website, platform)
        VALUES (?, ?, ?, ?, ?, ?, 'Ribeirão Preto', 'SP', ?, ?, 'universal')
        ON CONFLICT(id) DO UPDATE SET
            neighborhood = excluded.neighborhood,
            address = excluded.address,
            whatsapp = CASE WHEN excluded.whatsapp != '' THEN excluded.whatsapp ELSE stores.whatsapp END,
            website = excluded.website
        """, (store_id, name, slug, category, neighborhood, address, re.sub(r"\D", "", phone), website))

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10.0, verify=False) as client:
        platform = await detect_ecommerce_platform(website, client)
        print(f"[i] Loja '{name}': Plataforma = '{platform}'")

    saved_count = 0
    if platform == "tray":
        sitemap = website.rstrip("/") + "/sitemap.xml"
        await crawl_tray_full(store_id, sitemap)
        saved_count = 1
    elif platform == "vtex":
        await crawl_vtex_all(store_id, website)
        saved_count = 1
    elif platform == "shopify":
        saved_count = await crawl_shopify(store_id, website)
    elif platform == "woocommerce":
        saved_count = await crawl_woocommerce(store_id, website)
    elif platform in ("nuvemshop", "loja_integrada", "schema_product"):
        saved_count = await crawl_jsonld_universal(store_id, website, f"crawler_{platform}")

    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE discovered_stores SET status = 'imported', platform = ? WHERE name = ?", (platform, name))
        c.execute("UPDATE stores SET platform = ? WHERE id = ?", (platform, store_id))

    return saved_count


async def ingest_all_discovered_with_websites(backfill_platforms: bool = False, limit: int = None):
    """
    Processa as lojas com website para extração de produtos.
    Se backfill_platforms=True, re-processa também as lojas WooCommerce, Shopify e Nuvemshop
    que haviam sido marcadas como 'imported' na versão antiga sem extrair seus produtos.
    """
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        if backfill_platforms:
            c.execute("""
            SELECT d.* FROM discovered_stores d
            WHERE d.website IS NOT NULL AND d.website != ''
              AND (d.status != 'imported' OR d.platform IN ('woocommerce', 'shopify', 'nuvemshop'))
            """)
        else:
            c.execute("SELECT * FROM discovered_stores WHERE website IS NOT NULL AND website != '' AND status != 'imported'")
        rows = [dict(r) for r in c.fetchall()]

    if limit:
        rows = rows[:limit]

    print(f"\n[*] Encontradas {len(rows)} lojas para extração de produtos...")
    total_stores_with_items = 0

    for idx, store in enumerate(rows, 1):
        print(f"\n[{idx}/{len(rows)}] ---> Processando: {store['name']} ({store['website']})...")
        try:
            count = await process_and_ingest_store(store)
            if count > 0:
                total_stores_with_items += 1
        except Exception as e:
            print(f"[!] Erro ao processar loja {store['name']}: {e}")

    print(f"\n[✓] Extração finalizada! Novas lojas com catálogo abastecido: {total_stores_with_items}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extrator Universal de Produtos E-commerce")
    parser.add_argument("--backfill", action="store_true", help="Extrair produtos das lojas WooCommerce, Shopify e Nuvemshop")
    parser.add_argument("--limit", type=int, default=None, help="Limite de lojas para processar nesta execução")
    args = parser.parse_args()

    asyncio.run(ingest_all_discovered_with_websites(backfill_platforms=args.backfill, limit=args.limit))
