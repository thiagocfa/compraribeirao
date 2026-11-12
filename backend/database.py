import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "compraribeirao.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela de Lojas de Ribeirão Preto
    cursor.execute("""
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
        platform TEXT, -- 'vtex', 'tray', 'manual'
        is_sponsored BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Tabela de Produtos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL,
        sku TEXT,
        title TEXT NOT NULL,
        description TEXT,
        price REAL,
        original_price REAL,
        category TEXT,
        brand TEXT,
        image_url TEXT,
        product_url TEXT NOT NULL,
        in_stock BOOLEAN DEFAULT 1,
        source_type TEXT DEFAULT 'crawler', -- 'crawler', 'manual', 'api'
        is_sponsored BOOLEAN DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (store_id) REFERENCES stores(id)
    )
    """)

    # Tabela de Busca Textual Rápida (FTS5)
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
        product_id UNINDEXED,
        title,
        brand,
        category,
        description,
        store_name,
        neighborhood,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """)

    # Tabela de Espaços Publicitários (Anúncios Patrocinados Locais)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ad_banners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        sponsor_name TEXT NOT NULL,
        image_url TEXT,
        target_url TEXT NOT NULL,
        position TEXT DEFAULT 'top_banner', -- 'top_banner', 'search_inline', 'sidebar'
        active BOOLEAN DEFAULT 1,
        clicks INTEGER DEFAULT 0,
        impressions INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Banco de dados SQLite com FTS5 inicializado com sucesso!")
