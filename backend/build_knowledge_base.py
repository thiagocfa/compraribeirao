"""
Script de Inteligência Local - CompraRibeirão
Condensa o banco bruto (415 MB, 170k produtos) em um Knowledge Base ultraleve (compraribeirao_publico.db, ~5 MB).
Extrai marcas, categorias, termos-chave, amostras de estoque, coordenadas geográficas e cria índice FTS5.
"""

import sqlite3
import os
import re
import csv
import json
import hashlib
from collections import Counter

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao.db")
PUBLIC_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao_publico.db")
CSV_PATH = os.path.join(ROOT_DIR, "empresas_ribeirao_preto.csv")

# Centróides conhecidos de bairros em Ribeirão Preto (lat, lng)
NEIGHBORHOOD_COORDS = {
    "centro": (-21.1775, -47.8103),
    "campos elísios": (-21.1610, -47.8030),
    "campos elisios": (-21.1610, -47.8030),
    "ipiranga": (-21.1550, -47.8200),
    "alto do ipiranga": (-21.1650, -47.8250),
    "alto da boa vista": (-21.1960, -47.8120),
    "jardim paulista": (-21.1730, -47.7950),
    "jardim paulistano": (-21.1760, -47.7900),
    "vila tibério": (-21.1750, -47.8220),
    "vila tiberio": (-21.1750, -47.8220),
    "vila virgínia": (-21.1920, -47.8280),
    "vila virginia": (-21.1920, -47.8280),
    "nova aliança": (-21.2220, -47.8280),
    "nova alianca": (-21.2220, -47.8280),
    "jardim botânico": (-21.2150, -47.8080),
    "jardim botanico": (-21.2150, -47.8080),
    "ribeirânia": (-21.1910, -47.7810),
    "ribeirania": (-21.1910, -47.7810),
    "jardim irajá": (-21.2050, -47.8100),
    "jardim iraja": (-21.2050, -47.8100),
    "bonfim paulista": (-21.2780, -47.8230),
    "vila seixas": (-21.1830, -47.8050),
    "jardim califórnia": (-21.2010, -47.8250),
    "jardim california": (-21.2010, -47.8250),
    "castelo branco": (-21.1800, -47.7880),
    "planalto verde": (-21.1420, -47.8510),
    "sumarezinho": (-21.1630, -47.8350),
    "parque industrial lagoinha": (-21.1850, -47.7650),
    "lagoinha": (-21.1850, -47.7650),
    "vila monte alegre": (-21.1680, -47.8420),
    "vila ana maria": (-21.1950, -47.8010),
    "vila do golfe": (-21.2350, -47.8350),
    "jardim sao luiz": (-21.1980, -47.8150),
    "jardim são luiz": (-21.1980, -47.8150),
    "jardim sumaré": (-21.1880, -47.8120),
    "jardim sumare": (-21.1880, -47.8120),
    "boulevard": (-21.1820, -47.8140),
    "jardim américa": (-21.1930, -47.8190),
    "jardim america": (-21.1930, -47.8190),
    "quintino facci ii": (-21.1350, -47.7850),
    "simioni": (-21.1290, -47.7980),
    "adão do carmo leonel": (-21.2180, -47.8390),
    "jardim palmeiras": (-21.1550, -47.7800),
    "jardim recreio": (-21.1580, -47.8550)
}

CITY_CENTROID = (-21.1775, -47.8103)

STOPWORDS = {
    "de", "da", "do", "das", "dos", "em", "para", "com", "por", "sem", "ou", "e", "a", "o", "as", "os",
    "um", "uma", "uns", "umas", "no", "na", "nos", "nas", "ao", "aos", "se", "que", "cm", "mm", "m",
    "kg", "g", "ml", "l", "un", "pct", "ref", "tipo", "mod", "kit", "par", "peca", "cx", "pecas",
    "unidades", "geral", "diversos", "diversas", "produto", "produtos", "fabricante", "original",
    "novo", "nova", "preto", "ribeirao", "brasil", "loja", "ltda", "me", "epp"
}

def clean_neighborhood_name(raw_name: str) -> str:
    """Limpa números de sala, andar ou códigos sujos no nome do bairro."""
    if not raw_name:
        return "Ribeirão Preto"
    
    # Se tiver hífen com números antes (ex: '103/104 - Jardim California' ou '4º Andar sala 415 - Jardim Palma')
    parts = raw_name.split("-")
    if len(parts) > 1 and any(char.isdigit() for char in parts[0]):
        cleaned = parts[-1].strip()
    else:
        cleaned = raw_name.strip()
    
    # Remove sufixos como ", Ribeirão Preto - SP"
    cleaned = re.sub(r",?\s*Ribeir[aã]o Preto.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*SP.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or "Ribeirão Preto"

def sanitize_phone(raw_phone: str) -> str:
    """Extrai apenas dígitos e garante código 5516..."""
    if not raw_phone:
        return ""
    digits = re.sub(r"\D", "", raw_phone)
    if not digits:
        return ""
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11): # ex: 16992231607 ou 1639636414
        return "55" + digits
    if len(digits) in (8, 9): # sem DDD, adiciona 16
        return "5516" + digits
    return digits

def get_jitter(store_id: str, scale: float = 0.0035):
    """Gera um pequeno deslocamento determinístico para lojas no mesmo bairro não sobreporem o mesmo pixel."""
    h = int(hashlib.md5(store_id.encode("utf-8")).hexdigest(), 16)
    dx = ((h % 1000) / 500.0 - 1.0) * scale
    dy = (((h // 1000) % 1000) / 500.0 - 1.0) * scale
    return dx, dy

def load_csv_coords():
    """Carrega coordenadas exatas extraídas do Google Maps via CSV."""
    coords_map = {}
    if not os.path.exists(CSV_PATH):
        return coords_map
    
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            r = csv.reader(f, delimiter=";")
            header = next(r, None)
            for row in r:
                if len(row) >= 9:
                    name = row[1].strip().lower()
                    gmaps_link = row[8]
                    match = re.search(r"!3d(-?21\.\d+)!4d(-?47\.\d+)", gmaps_link)
                    if match:
                        coords_map[name] = (float(match.group(1)), float(match.group(2)))
    except Exception as e:
        print(f"Aviso ao ler CSV: {e}")
    return coords_map

def build_knowledge_base():
    print(f"Iniciando construção do Knowledge Base Local...")
    print(f"Lendo banco bruto: {RAW_DB_PATH}")
    
    if not os.path.exists(RAW_DB_PATH):
        print(f"Erro: Banco bruto {RAW_DB_PATH} não encontrado.")
        return

    csv_coords = load_csv_coords()
    print(f"Coordenadas exatas carregadas do CSV: {len(csv_coords)}")

    # Conectar ao banco bruto
    raw_conn = sqlite3.connect(RAW_DB_PATH)
    raw_conn.row_factory = sqlite3.Row
    raw_c = raw_conn.cursor()

    # Recriar banco público limpo
    if os.path.exists(PUBLIC_DB_PATH):
        try:
            os.remove(PUBLIC_DB_PATH)
        except Exception:
            pass

    pub_conn = sqlite3.connect(PUBLIC_DB_PATH)
    pub_c = pub_conn.cursor()

    # Configurar WAL e performance
    pub_conn.execute("PRAGMA journal_mode=WAL;")
    pub_conn.execute("PRAGMA synchronous=NORMAL;")

    # Criar tabelas
    pub_c.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        category TEXT,
        neighborhood TEXT,
        address TEXT,
        city TEXT DEFAULT 'Ribeirão Preto',
        state TEXT DEFAULT 'SP',
        whatsapp TEXT,
        website TEXT,
        logo_url TEXT,
        latitude REAL,
        longitude REAL,
        is_sponsored INTEGER DEFAULT 0,
        has_catalog INTEGER DEFAULT 0,
        product_count INTEGER DEFAULT 0,
        top_categories TEXT,
        top_brands TEXT,
        keywords TEXT,
        ai_summary TEXT,
        sample_products TEXT
    )
    """)

    pub_c.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS stores_search_fts USING fts5(
        store_id UNINDEXED,
        name,
        category,
        neighborhood,
        top_categories,
        top_brands,
        keywords,
        ai_summary,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """)

    pub_c.execute("""
    CREATE TABLE IF NOT EXISTS ad_banners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        sponsor_name TEXT NOT NULL,
        image_url TEXT,
        target_url TEXT NOT NULL,
        position TEXT DEFAULT 'top_banner',
        active BOOLEAN DEFAULT 1,
        clicks INTEGER DEFAULT 0,
        impressions INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Copiar banners de anúncios
    banners = raw_c.execute("SELECT title, sponsor_name, image_url, target_url, position, active FROM ad_banners").fetchall()
    for b in banners:
        pub_c.execute("""
        INSERT INTO ad_banners (title, sponsor_name, image_url, target_url, position, active)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (b["title"], b["sponsor_name"], b["image_url"], b["target_url"], b["position"], b["active"]))

    # Buscar todas as lojas
    stores = raw_c.execute("""
        SELECT id, name, slug, category, neighborhood, address, city, state, whatsapp, website, logo_url, is_sponsored
        FROM stores
        ORDER BY is_sponsored DESC, name ASC
    """).fetchall()

    print(f"Processando {len(stores)} lojas de Ribeirão Preto...")

    total_inserted = 0

    for store in stores:
        store_id = store["id"]
        store_name = store["name"]
        slug = store["slug"]
        category = store["category"] or "Comércio Local"
        raw_neighborhood = store["neighborhood"] or ""
        neighborhood = clean_neighborhood_name(raw_neighborhood)
        address = store["address"] or f"{neighborhood}, Ribeirão Preto - SP"
        raw_phone = store["whatsapp"] or ""
        whatsapp = sanitize_phone(raw_phone)
        website = store["website"] or ""
        logo_url = store["logo_url"] or ""
        is_sponsored = 1 if store["is_sponsored"] else 0

        # Determinar coordenadas
        name_key = store_name.strip().lower()
        lat, lng = None, None
        
        # 1. Match no CSV
        if name_key in csv_coords:
            lat, lng = csv_coords[name_key]
        else:
            # 2. Match aproximado no bairro
            neigh_key = neighborhood.lower()
            found_coord = False
            for k, coords in NEIGHBORHOOD_COORDS.items():
                if k in neigh_key or neigh_key in k:
                    dx, dy = get_jitter(store_id)
                    lat, lng = coords[0] + dx, coords[1] + dy
                    found_coord = True
                    break
            
            # 3. Fallback: Centróide da cidade com dispersão suave
            if not found_coord:
                dx, dy = get_jitter(store_id, scale=0.015)
                lat, lng = CITY_CENTROID[0] + dx, CITY_CENTROID[1] + dy

        # Analisar produtos da loja no banco bruto
        products = raw_c.execute("""
            SELECT title, category, brand, price, product_url, image_url
            FROM products
            WHERE store_id = ?
        """, (store_id,)).fetchall()

        product_count = len(products)
        has_catalog = 1 if product_count > 0 else 0

        top_brands_list = []
        top_cats_list = []
        keywords_list = []
        sample_products_list = []
        ai_summary = ""

        if has_catalog:
            brand_counter = Counter()
            cat_counter = Counter()
            word_counter = Counter()

            for p in products:
                title = p["title"] or ""
                cat = p["category"] or ""
                brand = p["brand"] or ""

                if brand and len(brand) > 1 and brand.lower() not in STOPWORDS:
                    brand_counter[brand.strip()] += 1
                if cat and len(cat) > 1 and cat.lower() not in STOPWORDS:
                    # Limpar hierarquia de categorias (ex: "Casa > Banheiro > Torneiras")
                    for subcat in cat.split(">"):
                        subcat_clean = subcat.strip()
                        if len(subcat_clean) > 2 and subcat_clean.lower() not in STOPWORDS:
                            cat_counter[subcat_clean] += 1

                # Extrair palavras do título
                for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", title.lower()):
                    if w not in STOPWORDS and not w.isdigit():
                        word_counter[w] += 1

            top_brands_list = [b for b, _ in brand_counter.most_common(12)]
            top_cats_list = [c for c, _ in cat_counter.most_common(10)]
            keywords_list = [w for w, _ in word_counter.most_common(40)]

            # Selecionar até 6 produtos de amostra representativos com foto e preço
            for p in products[:15]:
                if p["title"] and len(sample_products_list) < 6:
                    sample_products_list.append({
                        "title": p["title"][:70],
                        "price": p["price"] if p["price"] else None,
                        "url": p["product_url"],
                        "image": p["image_url"] if p["image_url"] else None
                    })

            # Gerar resumo amigável de catálogo
            brands_str = ", ".join(top_brands_list[:4]) if top_brands_list else ""
            cats_str = ", ".join(top_cats_list[:3]) if top_cats_list else ""
            
            summary_parts = [f"Loja física com catálogo disponível no {neighborhood}."]
            if cats_str:
                summary_parts.append(f"Destaques: {cats_str}.")
            if brands_str:
                summary_parts.append(f"Principais marcas: {brands_str}.")
            ai_summary = " ".join(summary_parts)

        else:
            # Loja física sem catálogo integrado (extrair inteligência de setor/nome/categoria)
            # Limpar termos redundantes de categoria ("ribeirao preto")
            clean_cat = re.sub(r"\bribeir[aã]o preto\b", "", category, flags=re.IGNORECASE).strip()
            cat_words = [w for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", clean_cat.lower()) if w not in STOPWORDS]
            name_words = [w for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", store_name.lower()) if w not in STOPWORDS]
            
            keywords_list = list(dict.fromkeys(cat_words + name_words))
            top_cats_list = [clean_cat.title()] if clean_cat else ["Comércio Local"]
            
            ai_summary = f"Estabelecimento comercial físico localizado no bairro {neighborhood}. Atendimento presencial e consultas via WhatsApp."

        top_categories_str = ", ".join(top_cats_list)
        top_brands_str = ", ".join(top_brands_list)
        keywords_str = ", ".join(keywords_list)
        sample_products_json = json.dumps(sample_products_list, ensure_ascii=False)

        # Inserir na tabela stores
        pub_c.execute("""
        INSERT INTO stores (
            id, name, slug, category, neighborhood, address, city, state, whatsapp, website, logo_url,
            latitude, longitude, is_sponsored, has_catalog, product_count, top_categories, top_brands,
            keywords, ai_summary, sample_products
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_id, store_name, slug, category, neighborhood, address, "Ribeirão Preto", "SP",
            whatsapp, website, logo_url, lat, lng, is_sponsored, has_catalog, product_count,
            top_categories_str, top_brands_str, keywords_str, ai_summary, sample_products_json
        ))

        # Inserir na tabela virtual FTS5
        pub_c.execute("""
        INSERT INTO stores_search_fts (
            store_id, name, category, neighborhood, top_categories, top_brands, keywords, ai_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_id, store_name, category, neighborhood, top_categories_str, top_brands_str, keywords_str, ai_summary
        ))

        total_inserted += 1

    # Criar índices úteis
    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_stores_neighborhood ON stores(neighborhood);")
    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_stores_sponsored ON stores(is_sponsored);")
    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_stores_has_catalog ON stores(has_catalog);")

    pub_conn.commit()

    # Otimizar FTS5
    pub_c.execute("INSERT INTO stores_search_fts(stores_search_fts) VALUES('optimize');")
    pub_conn.commit()

    # Fechar conexões
    raw_conn.close()
    pub_conn.close()

    file_size_mb = os.path.getsize(PUBLIC_DB_PATH) / (1024 * 1024)
    print(f"\nSucesso absoluto! {total_inserted} lojas sintetizadas.")
    print(f"Banco leve gerado: {PUBLIC_DB_PATH} ({file_size_mb:.2f} MB)")

if __name__ == "__main__":
    build_knowledge_base()
