from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import sqlite3
from typing import Optional, List
import re

# Garante que o diretório backend esteja no sys.path
sys.path.append(os.path.dirname(__file__))
from database import get_connection, db_transaction
import search_terms
import crawlers.universal_crawler as universal_crawler

app = FastAPI(title="CompraRibeirão API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/search-terms")
def get_terms():
    return search_terms.list_search_terms()

@app.post("/api/search-terms")
def create_term(term: str = Query(..., description="Novo termo de busca"), category: str = Query("Geral", description="Categoria do setor")):
    search_terms.add_search_term(term, category)
    return {"status": "success", "message": f"Termo '{term}' adicionado com sucesso!"}

@app.post("/api/ingest-discovered")
async def trigger_ingestion():
    import asyncio
    asyncio.create_task(universal_crawler.ingest_all_discovered_with_websites())
    return {"status": "success", "message": "Captura de produtos das lojas descobertas iniciada em segundo plano!"}

@app.get("/api/discovered")
def get_discovered_stores():
    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM discovered_stores ORDER BY id DESC")
        return [dict(r) for r in c.fetchall()]

@app.post("/api/discover")
async def trigger_discovery(query: str = Query(..., description="Termo para buscar no Google Maps (ex: pet shop, games, sapatos)")):
    from discovery_gmaps import scrape_google_maps_stores
    results = await scrape_google_maps_stores(query, max_results=12)
    return {
        "status": "success",
        "query": query,
        "discovered_count": len(results),
        "stores": results
    }

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

@app.get("/api/stats")
def get_stats():
    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM products WHERE in_stock = 1")
        total_products = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM stores")
        total_stores = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT neighborhood) FROM stores WHERE neighborhood IS NOT NULL")
        total_neighborhoods = c.fetchone()[0]
        
        return {
            "products_count": total_products,
            "stores_count": total_stores,
            "neighborhoods_count": total_neighborhoods,
            "city": "Ribeirão Preto - SP"
        }

@app.get("/api/neighborhoods")
def get_neighborhoods():
    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT DISTINCT s.neighborhood 
        FROM stores s
        JOIN products p ON s.id = p.store_id
        WHERE s.neighborhood IS NOT NULL AND s.neighborhood != ''
        ORDER BY s.neighborhood ASC
        """)
        return [r[0] for r in c.fetchall()]

@app.get("/api/stores")
def get_stores():
    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT s.id, s.name, s.neighborhood, COUNT(p.id) as product_count 
        FROM stores s 
        JOIN products p ON s.id = p.store_id 
        GROUP BY s.id
        HAVING product_count > 0
        ORDER BY s.is_sponsored DESC, s.name ASC
        """)
        return [dict(r) for r in c.fetchall()]

@app.get("/api/ads")
def get_ads(position: Optional[str] = None):
    with db_transaction() as conn:
        c = conn.cursor()
        if position:
            c.execute("SELECT * FROM ad_banners WHERE active = 1 AND position = ? ORDER BY id DESC", (position,))
        else:
            c.execute("SELECT * FROM ad_banners WHERE active = 1 ORDER BY id DESC")
        return [dict(r) for r in c.fetchall()]

@app.get("/api/search")
def search_products(
    q: Optional[str] = Query(None, description="Termo de pesquisa (ex: embreagem, porcelanato, parafuso)"),
    store_id: Optional[str] = None,
    neighborhood: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 40,
    offset: int = 0
):
    with db_transaction() as conn:
        c = conn.cursor()

        params = []
        where_clauses = ["p.in_stock = 1"]

        if store_id:
            where_clauses.append("p.store_id = ?")
            params.append(store_id)

        if neighborhood:
            where_clauses.append("s.neighborhood = ?")
            params.append(neighborhood)

        if min_price is not None:
            where_clauses.append("p.price >= ?")
            params.append(min_price)

        if max_price is not None:
            where_clauses.append("p.price <= ?")
            params.append(max_price)

        if q and q.strip():
            words = re.findall(r'\w+', q.strip())
            if words:
                fts_query = " ".join([f'"{w}"*' for w in words])
                where_clauses.append("products_fts MATCH ?")
                params.append(fts_query)
                
                term_prefix = f"{words[0]}%"
                term_contain = f"%{words[0]}%"
                params.extend([term_prefix, term_contain])
                
                where_sql = " AND ".join(where_clauses)
                query_sql = f"""
                SELECT 
                    p.*,
                    s.name as store_name,
                    s.neighborhood as store_neighborhood,
                    s.address as store_address,
                    s.whatsapp as store_whatsapp,
                    s.logo_url as store_logo_url,
                    s.is_sponsored as store_is_sponsored
                FROM products_fts
                JOIN products p ON products_fts.product_id = p.id
                JOIN stores s ON p.store_id = s.id
                WHERE {where_sql}
                ORDER BY 
                    (CASE WHEN p.title LIKE ? THEN 0 WHEN p.title LIKE ? THEN 1 ELSE 2 END),
                    products_fts.rank ASC,
                    (p.price > 0) DESC
                LIMIT ? OFFSET ?
                """
                params.extend([limit, offset])
        else:
            where_sql = " AND ".join(where_clauses)
            query_sql = f"""
            SELECT 
                p.*,
                s.name as store_name,
                s.neighborhood as store_neighborhood,
                s.address as store_address,
                s.whatsapp as store_whatsapp,
                s.logo_url as store_logo_url,
                s.is_sponsored as store_is_sponsored
            FROM products p
            JOIN stores s ON p.store_id = s.id
            WHERE {where_sql}
            ORDER BY s.is_sponsored DESC, (p.price > 0) DESC, p.updated_at DESC
            LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

        count_sql = f"""
        SELECT COUNT(*) 
        FROM products p
        JOIN stores s ON p.store_id = s.id
        {"JOIN products_fts ON p.id = products_fts.product_id" if (q and q.strip()) else ""}
        WHERE {where_sql}
        """
        
        if q and q.strip():
            c.execute(count_sql, [fts_query])
        else:
            where_params = params[:-2]
            c.execute(count_sql, where_params)
        
        total_found = c.fetchone()[0]

        c.execute(query_sql, params)
        results = [dict(r) for r in c.fetchall()]

        return {
            "query": q,
            "total": total_found,
            "count": len(results),
            "limit": limit,
            "offset": offset,
            "results": results
        }

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
