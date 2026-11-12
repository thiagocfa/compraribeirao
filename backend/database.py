"""
================================================================================
MÓDULO DE GERENCIAMENTO DE BANCO DE DADOS (backend/database.py)
================================================================================
Objetivo:
  Centralizar as conexões SQLite do projeto CompraRibeirão, separando claramente
  os dois bancos da arquitetura:

  1. RAW_DB_PATH ('compraribeirao.db' ~ 415 MB):
     - Fica APENAS no computador local do desenvolvedor (ignorado no Git/Nuvem).
     - Armazena os dados brutos de mineração:
       * 'discovered_stores': Lojas avistadas pelo robô do Google Maps.
       * 'stores': Cadastro mestre das lojas físicas de Ribeirão Preto.
       * 'store_web_content': Textos brutos extraídos dos websites (título, meta, H1/H2, corpo).
       * 'store_ai_intelligence': Análises geradas pela IA local (Qwen 2.5 via Ollama).
       * 'products': Produtos unitários extraídos de lojas que possuem e-commerce.

  2. PUBLIC_DB_PATH ('compraribeirao_publico.db' ~ 3.10 MB):
     - Banco ultraleve gerado pelo script 'backend/build_knowledge_base.py'.
     - É o ÚNICO banco enviado para o GitHub e carregado pelo Render na nuvem.
     - Contém a síntese inteligente das lojas e o índice FTS5 BM25 para buscas < 3ms.

Como dar manutenção:
  - Todos os scripts de captura/IA usam get_connection(RAW_DB_PATH) ou db_transaction().
  - No PC local (onde 'compraribeirao.db' existe), DB_PATH aponta automaticamente para
    o banco bruto para que os crawlers gravem sempre no lugar certo.
================================================================================
"""

import sqlite3
import os
import time
from typing import Optional
from contextlib import contextmanager

# Diretório raiz do projeto (e:\Projetos\CompraRibeirao)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Caminhos absolutos dos dois bancos de dados
PUBLIC_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao_publico.db")
RAW_DB_PATH = os.path.join(ROOT_DIR, "compraribeirao.db")

# Flag que indica se estamos rodando no PC local de desenvolvimento (onde o banco bruto existe)
IS_LOCAL_DEV_PC = os.path.exists(RAW_DB_PATH)

# Para os scripts de pipeline/crawlers que chamam get_connection() sem parâmetros:
# No PC local, usa SEMPRE o banco bruto (RAW_DB_PATH). Na nuvem, usa o banco público.
DB_PATH = RAW_DB_PATH if IS_LOCAL_DEV_PC else PUBLIC_DB_PATH


def get_connection(db_target: Optional[str] = None) -> sqlite3.Connection:
    """
    Abre e retorna uma conexão SQLite otimizada com:
    - WAL Mode (Write-Ahead Logging): Permite leituras e escritas simultâneas sem travar.
    - Busy Timeout de 60s: Aguarda caso outro processo esteja gravando no mesmo instante.
    - Cache de 32 MB em RAM para acelerar consultas pesadas.
    """
    target = db_target or DB_PATH
    conn = sqlite3.connect(target, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA cache_size=-32000;")  # ~32 MB de cache em memória
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_transaction(db_target: Optional[str] = None, max_retries: int = 5, retry_delay: float = 1.0):
    """
    Gerenciador de contexto ('with db_transaction() as conn:') para transações seguras.
    - Faz commit automático ao final do bloco.
    - Faz rollback automático se ocorrer exceção.
    - Fecha a conexão SEMPRE ao sair do bloco (evita vazamento de locks no Windows).
    - Retenta automaticamente até 'max_retries' vezes se o banco estiver ocupado ('database is locked').
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
    """Executa uma função de banco de dados com retentativas automáticas caso ocorra lock temporário."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise


def init_db():
    """
    Inicializa todas as tabelas fundamentais do banco bruto local ('compraribeirao.db').
    Pode ser executado quantas vezes quiser sem apagar dados existentes (usa IF NOT EXISTS).
    """
    with db_transaction(RAW_DB_PATH) as conn:
        cursor = conn.cursor()

        # 1. Tabela de Lojas Físicas de Ribeirão Preto
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

        # 2. Tabela de Lojas Descobertas no Google Maps
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            neighborhood TEXT,
            address TEXT,
            phone TEXT,
            website TEXT,
            rating REAL,
            reviews_count INTEGER,
            maps_url TEXT,
            platform TEXT,
            has_ecommerce BOOLEAN DEFAULT 0,
            status TEXT DEFAULT 'pending',
            query_used TEXT,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, address)
        )
        """)

        # 3. Tabela de Conteúdo Textual Extraído dos Sites das Lojas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_web_content (
            store_id TEXT PRIMARY KEY,
            store_name TEXT,
            website TEXT NOT NULL,
            page_title TEXT,
            meta_description TEXT,
            h1_headings TEXT,
            h2_headings TEXT,
            body_text TEXT,
            raw_html_length INTEGER,
            status TEXT DEFAULT 'pending',
            error_msg TEXT,
            crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 4. Tabela de Inteligência Gerada pela IA Local (Qwen 2.5 via Ollama)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_ai_intelligence (
            store_id TEXT PRIMARY KEY,
            store_name TEXT NOT NULL,
            macro_categoria TEXT,
            subcategoria TEXT,
            especialidades TEXT,
            marcas_detectadas TEXT,
            resumo_inteligente TEXT,
            palavras_chave_busca TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 5. Tabela de Produtos Unitários (de lojas que possuem e-commerce)
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

        # 6. Tabela de Espaços Publicitários / Patrocínios
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
    print("[✓] Estrutura do banco bruto 'compraribeirao.db' verificada e pronta!")
