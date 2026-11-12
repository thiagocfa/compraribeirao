"""
Módulo de Inteligência Local - Enriquecimento Semântico via LLM Local (Qwen 2.5 / Ollama)
Processa os textos brutos das lojas de Ribeirão Preto, hierarquiza categorias, detecta marcas,
especialidades e palavras-chave comerciais, salvando tudo no banco bruto local ('compraribeirao.db').
"""

import sqlite3
import json
import os
import sys
import httpx
import time
import re

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BACKEND_DIR)
sys.path.append(ROOT_DIR)
from database import get_connection, db_transaction, RAW_DB_PATH

OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"

def init_ai_table():
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS store_ai_intelligence (
            store_id TEXT PRIMARY KEY,
            store_name TEXT NOT NULL,
            macro_categoria TEXT,
            subcategoria TEXT,
            especialidades TEXT, -- JSON Array
            marcas_detectadas TEXT, -- JSON Array
            resumo_inteligente TEXT,
            palavras_chave_busca TEXT, -- JSON Array
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

def build_prompt(store: dict) -> str:
    name = store.get("store_name") or store.get("name") or "Empresa"
    neighborhood = store.get("neighborhood") or "Ribeirão Preto"
    category = store.get("category") or ""
    title = store.get("page_title") or ""
    meta = store.get("meta_description") or ""
    headings = (store.get("h1_headings") or "") + " " + (store.get("h2_headings") or "")
    body = (store.get("body_text") or "")[:2000] # Limita a 2000 caracteres para velocidade máxima

    prompt = f"""Você é um analista especialista em comércio físico e categorização de lojas em Ribeirão Preto - SP.
Analise as informações do website e perfil da empresa a seguir e gere um resumo de inteligência comercial.

DADOS DA EMPRESA:
- Nome: {name}
- Bairro: {neighborhood} (Ribeirão Preto - SP)
- Ramo Cadastrado: {category}
- Título da Página: {title}
- Descrição: {meta}
- Cabeçalhos do Site: {headings[:400]}
- Conteúdo do Site: {body}

Gere uma resposta ESTRITAMENTE em formato JSON (sem explicações adicionais, sem markdown fora do JSON) com esta estrutura exata:
{{
  "macro_categoria": "Setor macro (ex: Automotivo, Construção, Ferramentas, Informática, Móveis, Óticas, etc.)",
  "subcategoria": "Nicho específico (ex: Baterias Automotivas, Tintas e Vernizes, Colchões, CFTV e Alarmes, etc.)",
  "especialidades": ["especialidade 1", "especialidade 2", "especialidade 3", "especialidade 4"],
  "marcas_detectadas": ["marca1", "marca2", "marca3"],
  "resumo_inteligente": "1 a 2 frases claras e objetivas em português explicando o que a loja física vende e seus pontos fortes no bairro {neighborhood}.",
  "palavras_chave_busca": ["palavra1", "palavra2", "palavra3", "palavra4", "palavra5", "palavra6", "palavra7", "palavra8"]
}}
"""
    return prompt

def process_single_store(client: httpx.Client, store: dict) -> dict:
    prompt = build_prompt(store)
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2, # Baixa temperatura para categorização precisa e determinística
            "num_predict": 450
        }
    }

    try:
        resp = client.post(OLLAMA_API_URL, json=payload, timeout=60.0)
        if resp.status_code == 200:
            result_json_str = resp.json().get("response", "{}")
            data = json.loads(result_json_str)
            return data
        else:
            print(f"[!] Erro Ollama HTTP {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        print(f"[!] Exceção ao consultar LLM: {e}")
        return None

def run_enrichment(limit: int = None):
    print("=" * 60)
    print(f"   COMPRARIBEIRÃO - ENRIQUECIMENTO COM LLM LOCAL ({MODEL_NAME})")
    print("=" * 60)

    init_ai_table()

    # Busca lojas com texto capturado que ainda não foram processadas pela IA
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT 
            s.id as store_id, s.name as store_name, s.neighborhood, s.category,
            w.page_title, w.meta_description, w.h1_headings, w.h2_headings, w.body_text
        FROM stores s
        JOIN store_web_content w ON s.id = w.store_id
        LEFT JOIN store_ai_intelligence ai ON s.id = ai.store_id
        WHERE w.status = 'success' AND (ai.store_id IS NULL)
        ORDER BY s.is_sponsored DESC, s.id ASC
        """)
        pending_stores = [dict(r) for r in c.fetchall()]

    if limit:
        pending_stores = pending_stores[:limit]

    print(f"[*] Total de lojas aguardando processamento da IA: {len(pending_stores)}")
    if not pending_stores:
        print("[✓] Todas as lojas já foram analisadas pela LLM local!")
        return

    processed_count = 0
    start_time = time.time()

    with httpx.Client(timeout=65.0) as client:
        for idx, store in enumerate(pending_stores, 1):
            name = store["store_name"]
            store_id = store["store_id"]
            print(f"\n[{idx}/{len(pending_stores)}] Analisando com LLM: {name} ({store['neighborhood']})...")

            t0 = time.time()
            ai_data = process_single_store(client, store)
            elapsed = time.time() - t0

            if ai_data:
                macro = ai_data.get("macro_categoria") or "Comércio Local"
                subcat = ai_data.get("subcategoria") or store.get("category") or "Geral"
                especialidades = json.dumps(ai_data.get("especialidades") or [], ensure_ascii=False)
                marcas = json.dumps(ai_data.get("marcas_detectadas") or [], ensure_ascii=False)
                resumo = ai_data.get("resumo_inteligente") or ""
                palavras = json.dumps(ai_data.get("palavras_chave_busca") or [], ensure_ascii=False)

                with db_transaction(RAW_DB_PATH) as conn:
                    c = conn.cursor()
                    c.execute("""
                    INSERT INTO store_ai_intelligence (
                        store_id, store_name, macro_categoria, subcategoria,
                        especialidades, marcas_detectadas, resumo_inteligente, palavras_chave_busca, processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(store_id) DO UPDATE SET
                        macro_categoria = excluded.macro_categoria,
                        subcategoria = excluded.subcategoria,
                        especialidades = excluded.especialidades,
                        marcas_detectadas = excluded.marcas_detectadas,
                        resumo_inteligente = excluded.resumo_inteligente,
                        palavras_chave_busca = excluded.palavras_chave_busca,
                        processed_at = CURRENT_TIMESTAMP
                    """, (store_id, name, macro, subcat, especialidades, marcas, resumo, palavras))

                processed_count += 1
                print(f"[✓] Concluído em {elapsed:.1f}s | {macro} -> {subcat}")
                print(f"    Resumo: {resumo}")
            else:
                print(f"[x] Falha ao processar loja {name}.")

    total_time = time.time() - start_time
    print(f"\n" + "=" * 60)
    print(f"[✓] Enriquecimento finalizado! {processed_count} lojas analisadas em {total_time:.1f} segundos.")
    print("=" * 60)

if __name__ == "__main__":
    run_enrichment()
