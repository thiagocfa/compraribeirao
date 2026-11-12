r"""
================================================================================
MÓDULO DE INTELIGÊNCIA ARTIFICIAL LOCAL (backend/enrich_with_llm.py)
================================================================================
Objetivo:
  Ler os textos brutos capturados dos websites das lojas físicas de Ribeirão Preto
  (tabela 'store_web_content' no banco 'compraribeirao.db') e utilizar a LLM local
  Qwen 2.5 (3B) via Ollama (100% gratuito, rodando na CPU/GPU do PC) para interpretar
  e hierarquizar cada estabelecimento.

O que este script gera para cada loja (salvo em 'store_ai_intelligence'):
  - macro_categoria: Setor macro comercial (ex: Ferramentas, Automotivo, Construção)
  - subcategoria: Nicho específico da loja (ex: Baterias Automotivas, Parafusos e Fixadores)
  - especialidades: Lista de até 4 produtos/serviços principais que a loja oferece
  - marcas_detectadas: Lista de marcas reais que a loja trabalha (ex: Makita, Moura, Suvinil)
  - resumo_inteligente: Texto curto e vendedor (1-2 frases) focado no comércio físico local
  - palavras_chave_busca: Sinônimos e termos que os moradores digitam ao procurar a loja

Como dar manutenção:
  - Para trocar o modelo de IA: altere a constante MODEL_NAME (ex: "qwen2.5:3b" ou "llama3.2:3b").
  - Para ajustar o que a IA extrai: edite o texto dentro da função build_prompt().
  - Se o servidor do Ollama não estiver aberto no Windows, a função ensure_ollama_running()
    inicia o executável do Ollama automaticamente em segundo plano!

Como executar via terminal:
  - Processar apenas lojas novas/pendentes:
      .\venv\Scripts\python backend/enrich_with_llm.py
  - Reprocessar TODAS as lojas desde o início (--force):
      .\venv\Scripts\python backend/enrich_with_llm.py --force
  - Testar em apenas 5 lojas (--limit 5):
      .\venv\Scripts\python backend/enrich_with_llm.py --limit 5 --force
================================================================================
"""

import json
import os
import sys
import subprocess
import httpx
import time
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BACKEND_DIR)
sys.path.append(ROOT_DIR)

from database import db_transaction, RAW_DB_PATH

# Configurações do servidor local Ollama
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/api/generate"
MODEL_NAME = "qwen2.5:3b"


def ensure_ollama_running() -> bool:
    """
    Verifica se o serviço local do Ollama está respondendo na porta 11434.
    Caso esteja desligado, localiza o executável no Windows e o inicia automaticamente
    em segundo plano sem abrir janela preta extra.
    """
    try:
        r = httpx.get(OLLAMA_BASE_URL, timeout=2.5)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    print("[*] Servidor Ollama não detectado na porta 11434. Iniciando automaticamente...")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    ollama_exe = os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")
    if not os.path.exists(ollama_exe):
        ollama_exe = "ollama"  # Tenta pelo PATH do sistema

    try:
        # Inicia 'ollama serve' em background silencioso no Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(
            [ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags
        )
        # Aguarda até 10 segundos para o servidor subir
        for _ in range(10):
            time.sleep(1.0)
            try:
                r = httpx.get(OLLAMA_BASE_URL, timeout=2.0)
                if r.status_code == 200:
                    print("[✓] Servidor Ollama iniciado com sucesso!")
                    return True
            except Exception:
                continue
    except Exception as e:
        print(f"[!] Não foi possível iniciar o Ollama automaticamente: {e}")

    return False


def init_ai_table():
    """Garante que a tabela 'store_ai_intelligence' exista no banco bruto local."""
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS store_ai_intelligence (
            store_id TEXT PRIMARY KEY,
            store_name TEXT NOT NULL,
            macro_categoria TEXT,
            subcategoria TEXT,
            especialidades TEXT, -- JSON Array de strings
            marcas_detectadas TEXT, -- JSON Array de strings
            resumo_inteligente TEXT,
            palavras_chave_busca TEXT, -- JSON Array de strings
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)


def build_prompt(store: dict) -> str:
    """
    Monta o prompt estruturado que é enviado para a LLM Qwen 2.5.
    Limita o texto bruto a 2.000 caracteres para manter o tempo de resposta em ~2-3s por loja.
    """
    name = store.get("store_name") or store.get("name") or "Empresa"
    neighborhood = store.get("neighborhood") or "Ribeirão Preto"
    category = store.get("category") or ""
    title = store.get("page_title") or ""
    meta = store.get("meta_description") or ""
    headings = (store.get("h1_headings") or "") + " " + (store.get("h2_headings") or "")
    body = (store.get("body_text") or "")[:2000]

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
    """Envia os dados de uma única loja para o Ollama e retorna o dicionário JSON estruturado."""
    prompt = build_prompt(store)
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2,  # Baixa temperatura = respostas factuais e sem invenções
            "num_predict": 450
        }
    }

    try:
        resp = client.post(OLLAMA_API_URL, json=payload, timeout=60.0)
        if resp.status_code == 200:
            result_json_str = resp.json().get("response", "{}")
            return json.loads(result_json_str)
        else:
            print(f"[!] Erro Ollama HTTP {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        print(f"[!] Exceção ao consultar LLM: {e}")
        return None


def run_enrichment(limit: int = None, force_reprocess: bool = False):
    """
    Executa o lote de enriquecimento com IA local.
    - Se force_reprocess=False (padrão): processa apenas lojas novas que ainda não têm registro em 'store_ai_intelligence'.
    - Se force_reprocess=True: reanalisa todas as lojas que possuem texto capturado.
    """
    print("=" * 64)
    print(f"   COMPRARIBEIRÃO - ENRIQUECIMENTO COM IA LOCAL ({MODEL_NAME})")
    print("=" * 64)

    if not ensure_ollama_running():
        print("[ERRO] O servidor Ollama não está rodando. Verifique se o Ollama está instalado.")
        return 0

    init_ai_table()

    # Seleciona as lojas com conteúdo textual extraído
    with db_transaction(RAW_DB_PATH) as conn:
        c = conn.cursor()
        if force_reprocess:
            c.execute("""
            SELECT 
                s.id as store_id, s.name as store_name, s.neighborhood, s.category,
                w.page_title, w.meta_description, w.h1_headings, w.h2_headings, w.body_text
            FROM stores s
            JOIN store_web_content w ON s.id = w.store_id
            WHERE w.status = 'success'
            ORDER BY s.is_sponsored DESC, s.id ASC
            """)
        else:
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

    print(f"[*] Total de lojas na fila da IA: {len(pending_stores)}")
    if not pending_stores:
        print("[✓] Todas as lojas com conteúdo textual já estão enriquecidas pela IA! (Use --force para reprocessar)")
        return 0

    processed_count = 0
    start_time = time.time()

    with httpx.Client(timeout=65.0) as client:
        for idx, store in enumerate(pending_stores, 1):
            name = store["store_name"]
            store_id = store["store_id"]
            print(f"\n[{idx}/{len(pending_stores)}] Analisando com IA: {name} ({store['neighborhood']})...", flush=True)

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
                print(f"[✓] Concluído em {elapsed:.1f}s | {macro} -> {subcat}", flush=True)
                print(f"    Resumo: {resumo}", flush=True)
            else:
                print(f"[x] Falha ao processar loja {name}.", flush=True)

    total_time = time.time() - start_time
    print("\n" + "=" * 64)
    print(f"[✓] Enriquecimento finalizado! {processed_count} lojas analisadas em {total_time:.1f} segundos.")
    print("    Próximo passo: execute 'python backend/build_knowledge_base.py' para atualizar o banco público.")
    print("=" * 64)
    return processed_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enriquecimento Semântico com IA Local (Qwen 2.5 via Ollama)")
    parser.add_argument("--limit", type=int, default=None, help="Limitar quantidade de lojas a processar")
    parser.add_argument("--force", action="store_true", help="Reprocessar mesmo as lojas que já têm análise da IA")
    args = parser.parse_args()

    run_enrichment(limit=args.limit, force_reprocess=args.force)
