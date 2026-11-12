import sqlite3
import os
import time
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
PUBLIC_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao_publico.db")
RAW_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao.db")

# Se o banco leve de inteligência local existir, usa ele como padrão na API pública
DB_PATH = PUBLIC_DB_PATH if os.path.exists(PUBLIC_DB_PATH) else RAW_DB_PATH

def get_connection(db_target: Optional[str] = None):
    """Retorna uma conexão SQLite com WAL mode, tolerância a concorrência e timeout de 60 segundos."""
    target = db_target or DB_PATH
    conn = sqlite3.connect(target, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA cache_size=-32000;") # 32 MB cache
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def db_transaction(db_target: Optional[str] = None, max_retries: int = 5, retry_delay: float = 1.0):
    """
    Gerenciador de contexto para transações seguras.
    Fecha a conexão SEMPRE (mesmo com erro) e retenta se o banco estiver momentaneamente ocupado.
    """
    for attempt in range(max_retries):
        conn = None
        try:
            conn = get_connection(db_target)
            yield conn
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

def execute_with_retry(func, *args, max_retries: int = 5, retry_delay: float = 1.0, **kwargs):
    """Executa uma função de banco de dados com retentativas automáticas se ocorrer lock."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise

def init_db():
    with db_transaction(RAW_DB_PATH) as conn:
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
            platform TEXT,
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
            source_type TEXT DEFAULT 'crawler',
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

        # Tabela de Espaços Publicitários
        cursor.execute("""
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

if __name__ == "__main__":
    init_db()
    print("Banco de dados SQLite configurado com sucesso!")
