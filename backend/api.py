from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import sqlite3
import json
import urllib.parse
from typing import Optional, List, Any
import re
import time

# Garante que o diretório backend esteja no sys.path
sys.path.append(os.path.dirname(__file__))
from database import get_connection, db_transaction, DB_PATH, PUBLIC_DB_PATH, RAW_DB_PATH
import search_terms

app = FastAPI(title="CompraRibeirão - Inteligência Comercial Local", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# Cache em memória para respostas instantâneas
_RAM_CACHE = {}

def get_from_cache(key: str, ttl_seconds: int = 300):
    entry = _RAM_CACHE.get(key)
    if entry and (time.time() - entry["time"] < ttl_seconds):
        return entry["data"]
    return None

def set_in_cache(key: str, data: Any):
    _RAM_CACHE[key] = {"data": data, "time": time.time()}

def format_whatsapp_url(phone: str, store_name: str, query: Optional[str] = None) -> str:
    """Gera link direto para WhatsApp com mensagem personalizada."""
    if not phone:
        return ""
    clean_digits = re.sub(r"\D", "", phone)
    if not clean_digits:
        return ""
    if not clean_digits.startswith("55"):
        clean_digits = "55" + clean_digits
    
    if query:
        msg = f"Olá, vi sua loja ({store_name}) no CompraRibeirão e gostaria de saber sobre disponibilidade de '{query}'."
    else:
        msg = f"Olá, vi sua loja ({store_name}) no CompraRibeirão e gostaria de tirar uma dúvida."
    
    encoded_msg = urllib.parse.quote(msg)
    return f"https://wa.me/{clean_digits}?text={encoded_msg}"

@app.get("/api/stats")
def get_stats():
    cached = get_from_cache("stats", ttl_seconds=300)
    if cached:
        return cached

    with db_transaction() as conn:
        c = conn.cursor()
        
        # Total de lojas
        c.execute("SELECT COUNT(*) FROM stores")
        total_stores = c.fetchone()[0]
        
        # Total de bairros
        c.execute("SELECT COUNT(DISTINCT neighborhood) FROM stores WHERE neighborhood IS NOT NULL AND neighborhood != ''")
        total_neighborhoods = c.fetchone()[0]
        
        # Lojas com catálogo detalhado
        try:
            c.execute("SELECT COUNT(*) FROM stores WHERE has_catalog = 1")
            with_catalog = c.fetchone()[0]
        except Exception:
            with_catalog = 0
            
        result = {
            "stores_count": total_stores,
            "neighborhoods_count": total_neighborhoods,
            "catalog_stores_count": with_catalog,
            "city": "Ribeirão Preto - SP",
            "version": "2.0-intel"
        }
        set_in_cache("stats", result)
        return result

@app.get("/api/neighborhoods")
def get_neighborhoods():
    cached = get_from_cache("neighborhoods_v2", ttl_seconds=600)
    if cached:
        return cached

    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT neighborhood, COUNT(*) as store_count
        FROM stores 
        WHERE neighborhood IS NOT NULL AND neighborhood != '' AND neighborhood != 'Ribeirão Preto'
        GROUP BY neighborhood
        HAVING store_count >= 1
        ORDER BY store_count DESC, neighborhood ASC
        """)
        rows = [{"name": r[0], "count": r[1]} for r in c.fetchall()]
        set_in_cache("neighborhoods_v2", rows)
        return rows

@app.get("/api/categories")
def get_categories():
    cached = get_from_cache("categories_list", ttl_seconds=600)
    if cached:
        return cached

    popular_categories = [
        {"id": "auto", "name": "Peças & Automotivo", "icon": "fa-car", "query": "auto peças baterias pneus"},
        {"id": "construcao", "name": "Construção & Tintas", "icon": "fa-trowel-bricks", "query": "materiais de construcao tintas hidráulica"},
        {"id": "ferramentas", "name": "Ferramentas & Indústria", "icon": "fa-wrench", "query": "ferramentas makita furadeiras parafusos"},
        {"id": "moveis", "name": "Móveis & Decoração", "icon": "fa-couch", "query": "moveis decoracao colchões cortinas"},
        {"id": "eletro", "name": "Eletrodomésticos & Clima", "icon": "fa-snowflake", "query": "ar condicionado refrigeracao fogao"},
        {"id": "informatica", "name": "Informática & Celulares", "icon": "fa-laptop", "query": "informatica computadores celulares telas"},
        {"id": "musica", "name": "Instrumentos Musicais", "icon": "fa-guitar", "query": "instrumentos musicais violao audio som"},
        {"id": "seguranca", "name": "Segurança & CFTV", "icon": "fa-video", "query": "cameras seguranca cftv alarmes interfonia"},
        {"id": "piscinas", "name": "Piscinas & Lazer", "icon": "fa-water-ladder", "query": "piscinas produtos piscina cloro bombas"},
        {"id": "oticas", "name": "Óticas & Óculos", "icon": "fa-glasses", "query": "oticas oculos lentes armacao"},
        {"id": "festas", "name": "Festas & Embalagens", "icon": "fa-cake-candles", "query": "artigos para festas descartaveis embalagens"}
    ]
    set_in_cache("categories_list", popular_categories)
    return popular_categories

@app.get("/api/ads")
def get_ads(position: Optional[str] = None):
    cache_key = f"ads_{position}"
    cached = get_from_cache(cache_key, ttl_seconds=600)
    if cached:
        return cached

    with db_transaction() as conn:
        c = conn.cursor()
        try:
            if position:
                c.execute("SELECT * FROM ad_banners WHERE active = 1 AND position = ? ORDER BY id DESC", (position,))
            else:
                c.execute("SELECT * FROM ad_banners WHERE active = 1 ORDER BY id DESC")
            rows = [dict(r) for r in c.fetchall()]
        except Exception:
            rows = []
            
        set_in_cache(cache_key, rows)
        return rows

@app.get("/api/local-search")
def local_search(
    q: Optional[str] = Query(None, description="O que você procura em Ribeirão Preto (ex: makita, embreagem, porcelanato, piscina, bateria)"),
    neighborhood: Optional[str] = Query(None, description="Filtrar por bairro em Ribeirão Preto"),
    limit: int = 40,
    offset: int = 0
):
    """
    Busca inteligente no comércio físico local de Ribeirão Preto.
    Localiza lojas especializadas, estoques, marcas, bairros, telefones e rotas.
    """
    cache_key = f"local_search_{q}_{neighborhood}_{limit}_{offset}"
    cached = get_from_cache(cache_key, ttl_seconds=120)
    if cached:
        return cached

    with db_transaction() as conn:
        c = conn.cursor()

        # Verifica se temos a tabela FTS5 de lojas
        c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='stores_search_fts'")
        has_fts = c.fetchone()[0] > 0

        where_clauses = []
        params = []

        if neighborhood and neighborhood.strip():
            where_clauses.append("s.neighborhood LIKE ?")
            params.append(f"%{neighborhood.strip()}%")

        if q and q.strip() and has_fts:
            # Tokenizar busca para FTS5
            raw_words = re.findall(r'[a-zA-ZÀ-ÿ0-9]+', q.strip().lower())
            # Filtrar palavras muito comuns
            stopwords = {"de", "da", "do", "para", "com", "em", "ribeirao", "preto", "loja"}
            words = [w for w in raw_words if w not in stopwords and len(w) > 1]
            if not words:
                words = raw_words

            fts_query = " ".join([f'"{w}"*' for w in words])
            where_clauses.append("stores_search_fts MATCH ?")
            params.append(fts_query)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            query_sql = f"""
            SELECT 
                s.id, s.name, s.slug, s.category, s.neighborhood, s.address, s.city, s.state,
                s.whatsapp, s.website, s.logo_url, s.latitude, s.longitude,
                s.is_sponsored, s.has_catalog, s.product_count,
                s.top_categories, s.top_brands, s.keywords, s.ai_summary, s.sample_products,
                bm25(stores_search_fts) as search_rank
            FROM stores_search_fts
            JOIN stores s ON stores_search_fts.store_id = s.id
            WHERE {where_sql}
            ORDER BY 
                s.is_sponsored DESC,
                bm25(stores_search_fts) ASC,
                s.has_catalog DESC,
                s.name ASC
            LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            count_sql = f"""
            SELECT COUNT(*)
            FROM stores_search_fts
            JOIN stores s ON stores_search_fts.store_id = s.id
            WHERE {where_sql}
            """
            c.execute(count_sql, params[:-2])
            total_found = c.fetchone()[0]

        else:
            # Busca geral sem termo ou com filtro de bairro
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            query_sql = f"""
            SELECT 
                s.id, s.name, s.slug, s.category, s.neighborhood, s.address, s.city, s.state,
                s.whatsapp, s.website, s.logo_url, s.latitude, s.longitude,
                s.is_sponsored, s.has_catalog, s.product_count,
                s.top_categories, s.top_brands, s.keywords, s.ai_summary, s.sample_products,
                0 as search_rank
            FROM stores s
            WHERE {where_sql}
            ORDER BY 
                s.is_sponsored DESC,
                s.has_catalog DESC,
                s.name ASC
            LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            count_sql = f"SELECT COUNT(*) FROM stores s WHERE {where_sql}"
            c.execute(count_sql, params[:-2])
            total_found = c.fetchone()[0]

        c.execute(query_sql, params)
        raw_rows = [dict(r) for r in c.fetchall()]

        # Processar cada loja para a interface
        stores_list = []
        for r in raw_rows:
            # WhatsApp link
            phone = r.get("whatsapp") or ""
            r["whatsapp_url"] = format_whatsapp_url(phone, r.get("name", "Loja"), q)
            
            # Formatar telefone legível (ex: (16) 99223-1607)
            clean_digits = re.sub(r"\D", "", phone)
            num_clean = clean_digits[2:] if clean_digits.startswith("55") else clean_digits
            if len(num_clean) in (10, 11):
                ddd = num_clean[:2]
                num = num_clean[2:]
                if len(num) == 9:
                    r["phone_display"] = f"({ddd}) {num[:5]}-{num[5:]}"
                else:
                    r["phone_display"] = f"({ddd}) {num[:4]}-{num[4:]}"
            else:
                r["phone_display"] = phone or "Consulte via WhatsApp"

            # Parse de sample_products JSON
            if r.get("sample_products"):
                try:
                    r["sample_products"] = json.loads(r["sample_products"])
                except Exception:
                    r["sample_products"] = []
            else:
                r["sample_products"] = []

            # Sanitizar marcas e categorias em listas limpas
            brands_str = r.get("top_brands") or ""
            r["brands_list"] = [b.strip() for b in brands_str.split(",") if b.strip()][:8]

            cats_str = r.get("top_categories") or ""
            r["categories_list"] = [c.strip() for c in cats_str.split(",") if c.strip()][:6]

            stores_list.append(r)

        result_payload = {
            "query": q,
            "neighborhood": neighborhood,
            "total": total_found,
            "count": len(stores_list),
            "limit": limit,
            "offset": offset,
            "stores": stores_list
        }

        set_in_cache(cache_key, result_payload)
        return result_payload

@app.get("/api/search")
def search_bridge(
    q: Optional[str] = Query(None),
    neighborhood: Optional[str] = None,
    limit: int = 40,
    offset: int = 0
):
    """Bridge de compatibilidade para buscas de produtos."""
    return local_search(q=q, neighborhood=neighborhood, limit=limit, offset=offset)

@app.get("/api/stores")
def get_stores():
    cached = get_from_cache("all_stores_simple", ttl_seconds=600)
    if cached:
        return cached

    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, name, neighborhood, category, is_sponsored, has_catalog, product_count
        FROM stores
        ORDER BY is_sponsored DESC, name ASC
        """)
        rows = [dict(r) for r in c.fetchall()]
        set_in_cache("all_stores_simple", rows)
        return rows

# Serve frontend
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "CompraRibeirão API está no ar! Frontend em construção."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
