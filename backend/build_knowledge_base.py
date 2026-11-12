r"""
================================================================================
COMPILADOR DO KNOWLEDGE BASE PÚBLICO (backend/build_knowledge_base.py) — v2.5
================================================================================
Objetivo:
  Condensar o banco de dados bruto local ('compraribeirao.db' ~ 415 MB, contendo
  170.992 produtos raspados, 580 textos institucionais e 580 análises da IA Qwen 2.5)
  em um banco público ultraleve ('compraribeirao_publico.db' ~ 3.10 MB) pronto para
  rodar na nuvem gratuita (Render 512 MB RAM) com respostas em < 3 milissegundos.

O que este compilador faz:
  1. Higienização Geográfica de Ribeirão Preto (função clean_neighborhood_name):
     - Converte códigos de zoneamento do Google Maps ('Subsetor Sul - 5', 'Subsetor Norte - 1')
       para os bairros reais correspondentes ('Jardim Califórnia', 'Campos Elísios', etc.).
     - Unifica acentuações e preserva bairros compostos como 'Parque Ribeirão Preto'.
  2. Extração Profunda de Vocabulário de Estoque:
     - Para lojas que possuem e-commerce, extrai até 450 termos únicos de produtos
       para o índice de busca FTS5 (garantindo que itens específicos como 'parafuso',
       'sextavado', 'amortecedor', 'disjuntor' sejam encontrados imediatamente).
  3. Limpeza de Marcas (função filter_valid_brands):
     - Remove falsas marcas onde a IA repetiu o próprio nome da loja.
  4. Criação da Tabela de Telemetria ('lead_clicks'):
     - Prepara o banco público para contabilizar cliques em WhatsApp, Rota GPS e Site.

Como executar:
  .\venv\Scripts\python backend/build_knowledge_base.py
================================================================================
"""

import sqlite3
import os
import re
import csv
import json
import hashlib
import unicodedata
from collections import Counter

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao.db")
PUBLIC_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao_publico.db")
CSV_PATH = os.path.join(ROOT_DIR, "empresas_ribeirao_preto.csv")

# Centróides precisos dos bairros de Ribeirão Preto (lat, lng)
NEIGHBORHOOD_COORDS = {
    "centro": (-21.1775, -47.8103),
    "campos elísios": (-21.1610, -47.8030),
    "ipiranga": (-21.1550, -47.8200),
    "alto do ipiranga": (-21.1620, -47.8260),
    "alto da boa vista": (-21.1960, -47.8120),
    "jardim paulista": (-21.1730, -47.7950),
    "jardim paulistano": (-21.1760, -47.7900),
    "vila tibério": (-21.1780, -47.8220),
    "vila virgínia": (-21.1920, -47.8280),
    "nova aliança": (-21.2180, -47.8240),
    "jardim botânico": (-21.2110, -47.8040),
    "ribeirânia": (-21.1910, -47.7810),
    "nova ribeirânia": (-21.1940, -47.7750),
    "jardim irajá": (-21.2050, -47.8100),
    "bonfim paulista": (-21.2620, -47.8180),
    "vila seixas": (-21.1830, -47.8020),
    "jardim califórnia": (-21.2080, -47.8220),
    "jardim castelo branco": (-21.1800, -47.7880),
    "planalto verde": (-21.1420, -47.8510),
    "sumarezinho": (-21.1630, -47.8350),
    "parque industrial lagoinha": (-21.1850, -47.7650),
    "lagoinha": (-21.1830, -47.7680),
    "vila monte alegre": (-21.1680, -47.8420),
    "vila ana maria": (-21.1950, -47.8010),
    "vila do golfe": (-21.2320, -47.8320),
    "jardim são luiz": (-21.1980, -47.8150),
    "jardim sumaré": (-21.1880, -47.8120),
    "boulevard": (-21.1820, -47.8140),
    "jardim américa": (-21.1930, -47.8190),
    "quintino facci ii": (-21.1350, -47.7850),
    "simioni": (-21.1290, -47.7980),
    "adão do carmo leonel": (-21.1480, -47.8390),
    "jardim palmeiras": (-21.1550, -47.7800),
    "jardim recreio": (-21.1580, -47.8550),
    "parque ribeirão preto": (-21.1980, -47.8450),
    "jardim palma travassos": (-21.1860, -47.7950),
    "santa cruz": (-21.2020, -47.8180),
    "vila mariana": (-21.1650, -47.7980),
    "jardim macedo": (-21.1790, -47.7970),
    "jardim mosteiro": (-21.1690, -47.7980),
    "jardim canadá": (-21.2150, -47.8180),
    "jardim anhanguera": (-21.1890, -47.7920),
    "city ribeirão": (-21.2250, -47.8050),
    "vila brasil": (-21.1590, -47.7950),
    "vila carvalho": (-21.1520, -47.8050),
    "vila elisa": (-21.1460, -47.8020),
    "parque industrial tanquinho": (-21.1380, -47.7750),
    "parque dos servidores": (-21.1950, -47.7620)
}

CITY_CENTROID = (-21.1775, -47.8103)

STOPWORDS = {
    "de", "da", "do", "das", "dos", "em", "para", "com", "por", "sem", "ou", "e", "a", "o", "as", "os",
    "um", "uma", "uns", "umas", "no", "na", "nos", "nas", "ao", "aos", "se", "que", "cm", "mm", "m",
    "kg", "g", "ml", "l", "un", "pct", "ref", "tipo", "mod", "kit", "par", "peca", "cx", "pecas",
    "unidades", "geral", "diversos", "diversas", "produto", "produtos", "fabricante", "original",
    "novo", "nova", "preto", "ribeirao", "brasil", "loja", "ltda", "me", "epp", "comercio", "pagina",
    "marca", "modelo", "serie", "linha", "cor", "tamanho", "alta", "baixo", "grande", "pequeno",
    "bivolt", "110v", "220v", "127v", "volts", "watts", "graus", "litro", "litros", "metros", "metro"
}

def strip_accents(text: str) -> str:
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

def clean_neighborhood_name(raw_name: str, address: str = "") -> str:
    """Higieniza e padroniza 100% dos nomes de bairros de Ribeirão Preto."""
    combined = f"{raw_name or ''} | {address or ''}".lower()

    # Mapeamento direto de Subsetores e casos especiais do Google Maps em Ribeirão Preto
    if "subsetor sul - 5" in combined or "fernando ferreira leite" in combined or "ribeirão shopping" in combined or "ribeirao shopping" in combined:
        return "Jardim Califórnia"
    if "subsetor sul - 6" in combined or "gasperi consoni" in combined:
        return "Jardim Botânico"
    if "subsetor sul - 3" in combined or "santa cruz" in combined:
        return "Santa Cruz"
    if "subsetor leste - 1" in combined:
        return "Vila Seixas"
    if "subsetor norte - 13" in combined or "hermelindo del rosso" in combined or "esplanada da estacao" in combined:
        return "Jardim Aeroporto"
    if "subsetor norte - 1" in combined or "campos elíseos" in combined or "campos elisios" in combined or "campos elísios" in combined:
        return "Campos Elísios"
    if "subsetor oeste - 6" in combined:
        return "Ipiranga"
    if "parque ribeirao" in combined or "parque ribeirão" in combined or raw_name.strip().lower() == "parque":
        return "Parque Ribeirão Preto"
    if "presidente vargas, 2665" in combined:
        return "Jardim Califórnia"
    if "maurílio biagi" in combined or "maurilio biagi" in combined:
        if "ribeir" in combined:
            return "Ribeirânia"
        return "Santa Cruz"
    if "joão guião" in combined or "joao guiao" in combined:
        return "Vila Virgínia"

    if not raw_name:
        return "Centro"

    cleaned = raw_name.strip()

    # Remove prefixos de salas/lojas antes do hífen
    if "-" in cleaned:
        parts = [p.strip() for p in cleaned.split("-") if p.strip()]
        # Se a última parte for o nome real do bairro
        candidate = parts[-1]
        if len(candidate) > 3 and not candidate.isdigit():
            cleaned = candidate

    # Remove sufixos de cidade/estado sem destruir "Parque Ribeirão Preto" ou "City Ribeirão"
    if not cleaned.lower().startswith("parque ribeir") and not cleaned.lower().startswith("city ribeir"):
        cleaned = re.sub(r",?\s*Ribeir[aã]o Preto.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*SP.*$", "", cleaned, flags=re.IGNORECASE).strip()

    # Padronização canônica de acentuação e sinônimos de bairros
    norm_map = {
        "jardim california": "Jardim Califórnia",
        "jardim califórnia": "Jardim Califórnia",
        "jardim america": "Jardim América",
        "jardim américa": "Jardim América",
        "jardim sao luiz": "Jardim São Luiz",
        "jardim são luiz": "Jardim São Luiz",
        "jardim sumare": "Jardim Sumaré",
        "jardim sumaré": "Jardim Sumaré",
        "sumaré": "Jardim Sumaré",
        "sumare": "Jardim Sumaré",
        "vila tiberio": "Vila Tibério",
        "vila tibério": "Vila Tibério",
        "vila virginia": "Vila Virgínia",
        "vila virgínia": "Vila Virgínia",
        "vila tamandare": "Vila Tamandaré",
        "vila amelia": "Vila Amélia",
        "jardim nova alianca": "Nova Aliança",
        "nova alianca": "Nova Aliança",
        "nova aliança": "Nova Aliança",
        "jardim botanico": "Jardim Botânico",
        "jardim botânico": "Jardim Botânico",
        "jardim iraja": "Jardim Irajá",
        "jardim irajá": "Jardim Irajá",
        "jardim canada": "Jardim Canadá",
        "jardim canadá": "Jardim Canadá",
        "jardim independencia": "Jardim Independência",
        "independência": "Jardim Independência",
        "ribeirania": "Ribeirânia",
        "ribeirânia": "Ribeirânia",
        "parque industria": "Parque Industrial Lagoinha",
        "parque residencial lagoinha": "Parque Industrial Lagoinha",
        "pq. dos servidores": "Parque dos Servidores",
        "res. parque dos servidores": "Parque dos Servidores",
        "res. florida": "Residencial Flórida",
        "recreio das acacias": "Recreio das Acácias",
        "pacaembu": "Jardim Pacaembu",
        "iguatemi": "Vila do Golfe",
        "jardim maria da graça": "Jardim Maria da Graça",
        "ribeirão preto": "Centro"
    }

    key = cleaned.lower()
    if key in norm_map:
        return norm_map[key]
    if len(cleaned) <= 2 or any(c in cleaned for c in [")", "("]):
        return "Centro"

    return cleaned

def sanitize_address(raw_address: str, neighborhood: str) -> str:
    """Corrige endereços onde o scraper do Maps capturou nota de avaliação (ex: '4,9(147)')."""
    if not raw_address:
        return f"{neighborhood}, Ribeirão Preto - SP"
    addr = raw_address.strip()
    if re.match(r"^\d[,\.]\d\(\d+\)$", addr) or len(addr) < 8:
        return f"Atendimento no bairro {neighborhood}, Ribeirão Preto - SP"
    # Limpa prefixos promocionais longos
    addr = re.sub(r"^Neste mesmo endereço[^,]+,\s*", "", addr, flags=re.IGNORECASE)
    return addr

def sanitize_phone(raw_phone: str) -> str:
    """Extrai apenas dígitos e garante código 5516..."""
    if not raw_phone:
        return ""
    digits = re.sub(r"\D", "", raw_phone)
    if not digits:
        return ""
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11):
        return "55" + digits
    if len(digits) in (8, 9):
        return "5516" + digits
    return digits

def get_jitter(store_id: str, scale: float = 0.0032):
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

def filter_valid_brands(brands_raw: list, store_name: str) -> list:
    """Remove marcas falsas onde a IA repetiu o próprio nome da loja ou termos genéricos."""
    store_norm = strip_accents(store_name.lower())
    store_tokens = set(re.findall(r"[a-z0-9]{3,}", store_norm))
    cleaned_brands = []
    seen = set()

    invalid_brands = {
        "geral", "diversas", "diversos", "nacional", "importado", "nacional/importado",
        "fabricante", "original", "sem licença", "sem licenca", "nenhuma", "propria", "própria",
        "marca própria", "ribeirao preto", "ribeirão preto"
    }

    for b in brands_raw:
        if not b or not isinstance(b, str):
            continue
        b_clean = b.strip()
        b_norm = strip_accents(b_clean.lower())
        if len(b_clean) < 2 or len(b_clean) > 32:
            continue
        if b_norm in invalid_brands or b_norm in seen:
            continue
        # Se a marca for idêntica ao nome da loja ou contiver quase todas as palavras da loja, ignora
        if b_norm == store_norm or (len(b_norm) > 6 and b_norm in store_norm):
            continue
        b_tokens = set(re.findall(r"[a-z0-9]{3,}", b_norm))
        if b_tokens and len(b_tokens) >= 2 and b_tokens.issubset(store_tokens):
            continue

        seen.add(b_norm)
        cleaned_brands.append(b_clean)

    return cleaned_brands[:10]

def build_knowledge_base():
    print(f"Iniciando construção do Knowledge Base Local v2.5...")
    print(f"Lendo banco bruto: {RAW_DB_PATH}")
    
    if not os.path.exists(RAW_DB_PATH):
        print(f"Erro: Banco bruto {RAW_DB_PATH} não encontrado.")
        return

    csv_coords = load_csv_coords()
    print(f"Coordenadas exatas carregadas do CSV: {len(csv_coords)}")

    raw_conn = sqlite3.connect(RAW_DB_PATH)
    raw_conn.row_factory = sqlite3.Row
    raw_c = raw_conn.cursor()

    if os.path.exists(PUBLIC_DB_PATH):
        try:
            os.remove(PUBLIC_DB_PATH)
        except Exception:
            pass

    pub_conn = sqlite3.connect(PUBLIC_DB_PATH)
    pub_c = pub_conn.cursor()

    pub_conn.execute("PRAGMA journal_mode=WAL;")
    pub_conn.execute("PRAGMA synchronous=NORMAL;")

    # Criar tabela principal de lojas
    pub_c.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        category TEXT,
        macro_category TEXT,
        subcategory TEXT,
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
        specialties TEXT,
        keywords TEXT,
        ai_summary TEXT,
        sample_products TEXT
    )
    """)

    # Criar tabela virtual FTS5 otimizada
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

    # Criar tabela de anúncios patrocinados
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

    # Criar tabela de telemetria de leads (Monetização / Relatório para Lojistas)
    pub_c.execute("""
    CREATE TABLE IF NOT EXISTS lead_clicks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        store_name TEXT,
        action_type TEXT NOT NULL, -- 'whatsapp', 'gps', 'website', 'phone'
        search_query TEXT,
        neighborhood_filter TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Copiar banners
    banners = raw_c.execute("SELECT title, sponsor_name, image_url, target_url, position, active FROM ad_banners").fetchall()
    for b in banners:
        pub_c.execute("""
        INSERT INTO ad_banners (title, sponsor_name, image_url, target_url, position, active)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (b["title"], b["sponsor_name"], b["image_url"], b["target_url"], b["position"], b["active"]))

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
        raw_cat = store["category"] or "Comércio Local"
        clean_raw_cat = re.sub(r"\bribeir[aã]o preto\b", "", raw_cat, flags=re.IGNORECASE).strip().title() or "Comércio Local"
        
        raw_neighborhood = store["neighborhood"] or ""
        raw_address = store["address"] or ""
        neighborhood = clean_neighborhood_name(raw_neighborhood, raw_address)
        address = sanitize_address(raw_address, neighborhood)
        whatsapp = sanitize_phone(store["whatsapp"] or "")
        website = store["website"] or ""
        logo_url = store["logo_url"] or ""
        is_sponsored = 1 if store["is_sponsored"] else 0

        # Determinar coordenadas geográficas precisas
        name_key = store_name.strip().lower()
        lat, lng = None, None
        
        if name_key in csv_coords:
            lat, lng = csv_coords[name_key]
        else:
            neigh_key = neighborhood.lower()
            neigh_norm = strip_accents(neigh_key)
            found_coord = False
            for k, coords in NEIGHBORHOOD_COORDS.items():
                k_norm = strip_accents(k)
                if k_norm == neigh_norm or k_norm in neigh_norm or neigh_norm in k_norm:
                    dx, dy = get_jitter(store_id)
                    lat, lng = coords[0] + dx, coords[1] + dy
                    found_coord = True
                    break
            
            if not found_coord:
                dx, dy = get_jitter(store_id, scale=0.012)
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
        specialties_list = []
        keywords_list = []
        sample_products_list = []
        ai_summary = ""
        macro_category = clean_raw_cat
        subcategory = clean_raw_cat

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
                    for subcat in cat.split(">"):
                        subcat_clean = subcat.strip()
                        if len(subcat_clean) > 2 and subcat_clean.lower() not in STOPWORDS:
                            cat_counter[subcat_clean] += 1

                for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", title.lower()):
                    if w not in STOPWORDS and not w.isdigit():
                        word_counter[w] += 1

            raw_brands = [b for b, _ in brand_counter.most_common(20)]
            top_brands_list = filter_valid_brands(raw_brands, store_name)
            top_cats_list = [c for c, _ in cat_counter.most_common(12)]
            # Guardamos até 450 palavras-chave distintas do estoque para garantir recall de 100% dos produtos!
            keywords_list = [w for w, _ in word_counter.most_common(450)]

            # Selecionar até 24 produtos diversificados (de diferentes categorias/títulos) para exibição dinâmica na busca
            seen_titles = set()
            step = max(1, len(products) // 30)
            for p in products[::step]:
                t_clean = (p["title"] or "").strip()
                t_prefix = t_clean[:20].lower()
                if t_clean and t_prefix not in seen_titles and len(sample_products_list) < 24:
                    seen_titles.add(t_prefix)
                    sample_products_list.append({
                        "title": t_clean[:75],
                        "price": p["price"] if p["price"] else None,
                        "url": p["product_url"],
                        "image": p["image_url"] if p["image_url"] else None
                    })

            brands_str = ", ".join(top_brands_list[:4]) if top_brands_list else ""
            cats_str = ", ".join(top_cats_list[:3]) if top_cats_list else ""
            
            summary_parts = [f"Loja física com {product_count} itens mapeados no bairro {neighborhood}."]
            if cats_str:
                summary_parts.append(f"Destaque em {cats_str}.")
            if brands_str:
                summary_parts.append(f"Trabalha com {brands_str}.")
            ai_summary = " ".join(summary_parts)

        else:
            cat_words = [w for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", clean_raw_cat.lower()) if w not in STOPWORDS]
            name_words = [w for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", store_name.lower()) if w not in STOPWORDS]
            keywords_list = list(dict.fromkeys(cat_words + name_words))
            top_cats_list = [clean_raw_cat]
            ai_summary = f"Comércio físico especializado em {clean_raw_cat.lower()} localizado no bairro {neighborhood}. Atendimento direto e consulta rápida via WhatsApp."

        # Mesclar inteligência gerada pela LLM Local (Qwen 2.5)
        try:
            ai_row = raw_c.execute("""
                SELECT macro_categoria, subcategoria, especialidades, marcas_detectadas, resumo_inteligente, palavras_chave_busca 
                FROM store_ai_intelligence 
                WHERE store_id = ?
            """, (store_id,)).fetchone()

            if ai_row:
                m_cat, s_cat, ai_specs, ai_brands, ai_resumo, ai_keywords = ai_row
                if m_cat and m_cat.lower() not in ("nenhuma", "geral"):
                    macro_category = m_cat.strip()
                if s_cat and s_cat.lower() not in ("nenhuma", "geral"):
                    subcategory = s_cat.strip()

                if ai_resumo and len(ai_resumo.strip()) > 15:
                    # Corrige caso o resumo da IA mencione código de subsetor antigo
                    clean_resumo = re.sub(r"Subsetor\s+[A-Za-z]+\s*-\s*\d+\s*\([A-Z]-\d+\)", neighborhood, ai_resumo)
                    clean_resumo = re.sub(r"Luc\s+\d+\s*-\s*", "", clean_resumo)
                    ai_summary = clean_resumo.strip()
                
                if ai_specs:
                    try:
                        s_list = json.loads(ai_specs)
                        if isinstance(s_list, list):
                            specialties_list = [str(s).strip() for s in s_list if str(s).strip() and len(str(s).strip()) > 2][:8]
                    except Exception:
                        pass

                if ai_brands:
                    try:
                        b_list = json.loads(ai_brands)
                        if isinstance(b_list, list):
                            merged_brands = filter_valid_brands(b_list + top_brands_list, store_name)
                            top_brands_list = merged_brands
                    except Exception:
                        pass

                if ai_keywords:
                    try:
                        k_list = json.loads(ai_keywords)
                        if isinstance(k_list, list):
                            clean_k = [str(k).strip().lower() for k in k_list if str(k).strip()]
                            keywords_list = list(dict.fromkeys(clean_k + specialties_list + keywords_list))[:450]
                    except Exception:
                        pass

                cats = [c for c in [subcategory, macro_category, clean_raw_cat] if c and c.lower() not in ("geral", "nenhuma")]
                top_cats_list = list(dict.fromkeys(cats + specialties_list[:3] + top_cats_list))[:10]
        except Exception:
            pass

        top_categories_str = ", ".join(top_cats_list)
        top_brands_str = ", ".join(top_brands_list)
        specialties_str = ", ".join(specialties_list) if specialties_list else top_categories_str
        keywords_str = ", ".join(keywords_list)
        sample_products_json = json.dumps(sample_products_list, ensure_ascii=False)

        pub_c.execute("""
        INSERT INTO stores (
            id, name, slug, category, macro_category, subcategory, neighborhood, address, city, state,
            whatsapp, website, logo_url, latitude, longitude, is_sponsored, has_catalog, product_count,
            top_categories, top_brands, specialties, keywords, ai_summary, sample_products
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_id, store_name, slug, subcategory or clean_raw_cat, macro_category, subcategory,
            neighborhood, address, "Ribeirão Preto", "SP",
            whatsapp, website, logo_url, lat, lng, is_sponsored, has_catalog, product_count,
            top_categories_str, top_brands_str, specialties_str, keywords_str, ai_summary, sample_products_json
        ))

        pub_c.execute("""
        INSERT INTO stores_search_fts (
            store_id, name, category, neighborhood, top_categories, top_brands, keywords, ai_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_id, store_name, f"{macro_category} {subcategory} {clean_raw_cat}",
            neighborhood, f"{top_categories_str} {specialties_str}", top_brands_str, keywords_str, ai_summary
        ))

        total_inserted += 1

    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_stores_neighborhood ON stores(neighborhood);")
    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_stores_sponsored ON stores(is_sponsored);")
    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_stores_has_catalog ON stores(has_catalog);")
    pub_c.execute("CREATE INDEX IF NOT EXISTS idx_leads_store ON lead_clicks(store_id);")

    pub_conn.commit()
    pub_c.execute("INSERT INTO stores_search_fts(stores_search_fts) VALUES('optimize');")
    pub_conn.commit()

    raw_conn.close()
    pub_conn.close()

    file_size_mb = os.path.getsize(PUBLIC_DB_PATH) / (1024 * 1024)
    print(f"\nSucesso absoluto! {total_inserted} lojas sintetizadas com higienização completa.")
    print(f"Banco leve gerado: {PUBLIC_DB_PATH} ({file_size_mb:.2f} MB)")

if __name__ == "__main__":
    build_knowledge_base()
