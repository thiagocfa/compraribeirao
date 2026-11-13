"""
================================================================================
SERVIDOR WEB & MOTOR DE BUSCA LOCAL (backend/api.py) — Versão 2.5
================================================================================
Objetivo:
  Servir a API rápida (< 3ms) e o Frontend do CompraRibeirão consumindo o banco
  público compilado ('compraribeirao_publico.db' ~ 3.10 MB), além de expor as
  rotas administrativas locais ('/api/admin/*') para o Painel de Controle de
  Manutenção quando executado no computador do desenvolvedor.

Como dar manutenção neste arquivo:
  1. Dicionário de Sinônimos (SYNONYM_MAP):
     - Adicione novos termos populares que os moradores de Ribeirão Preto buscam
       mapeando-os para as categorias/palavras técnicas das lojas.
  2. Pesos de Relevância FTS5 (função local_search):
     - A chamada 'bm25(stores_search_fts, 12.0, 10.0, 3.0, 9.0, 8.0, 5.0, 2.0)'
       define o peso de cada coluna: Nome (12), Categoria (10), Bairro (3),
       Top Categorias (9), Marcas (8), Palavras-chave (5), Resumo IA (2).
  3. Raio de Bairros Vizinhos:
     - Na função local_search, o limite padrão para sugerir lojas de bairros
       adjacentes é 4.5 km (variável 'dist_km > 4.5').
  4. Painel de Controle Web (/api/admin/*):
     - Só permite disparar capturas, IA e deploy se o arquivo 'compraribeirao.db'
       existir na máquina (ou seja, bloqueado automaticamente na nuvem Render).
================================================================================
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import sys
import json
import urllib.parse
import math
import unicodedata
import subprocess
import threading
from typing import Optional, List, Any, Dict
import re
import time

# Garante que o diretório backend e a raiz estejam no sys.path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
sys.path.append(BACKEND_DIR)
sys.path.append(ROOT_DIR)

from database import db_transaction, PUBLIC_DB_PATH, RAW_DB_PATH
from build_knowledge_base import NEIGHBORHOOD_COORDS, CITY_CENTROID


def get_system_diagnostics() -> dict:
    """
    Importa o diagnóstico do orquestrador apenas quando o Painel de Controle é aberto.
    Assim a API pública na nuvem não carrega Playwright/crawlers na inicialização
    (menos RAM e boot mais rápido no Render).
    """
    try:
        from run_pipeline import get_system_diagnostics as _diag
        return _diag()
    except Exception as e:
        return {
            "raw_db_exists": os.path.exists(RAW_DB_PATH),
            "public_db_exists": os.path.exists(PUBLIC_DB_PATH),
            "public_db_size_mb": round(os.path.getsize(PUBLIC_DB_PATH) / (1024 * 1024), 2) if os.path.exists(PUBLIC_DB_PATH) else 0,
            "error": str(e),
        }

app = FastAPI(title="CompraRibeirão - Inteligência Comercial Local", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

# ==============================================================================
# 1. CACHE EM MEMÓRIA RAM (Respostas em < 1ms para buscas repetidas)
# ==============================================================================
_RAM_CACHE: Dict[str, Dict[str, Any]] = {}


def get_from_cache(key: str, ttl_seconds: int = 180):
    """Retorna um valor do cache em memória se ainda estiver dentro do tempo de vida (TTL)."""
    entry = _RAM_CACHE.get(key)
    if entry and (time.time() - entry["time"] < ttl_seconds):
        return entry["data"]
    return None


def set_in_cache(key: str, data: Any):
    """Armazena um resultado no cache em memória."""
    _RAM_CACHE[key] = {"data": data, "time": time.time()}


def clear_all_cache():
    """Limpa todo o cache em memória (chamado automaticamente após recompilar o banco)."""
    _RAM_CACHE.clear()


# ==============================================================================
# 2. FUNÇÕES UTILITÁRIAS DE TEXTO, GEOLOCALIZAÇÃO E SINÔNIMOS
# ==============================================================================
def strip_accents(text: str) -> str:
    """Remove acentos de uma string para comparações insensíveis a acentuação."""
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula a distância física real em linha reta (km) entre duas coordenadas GPS
    usando a fórmula trigonométrica de Haversine.
    """
    R = 6371.0  # Raio médio da Terra em km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# Dicionário Semântico de Intenções e Sinônimos do Comércio Físico de Ribeirão Preto.
# Para adicionar novos sinônimos, basta incluir uma chave (sem acento) e a lista de termos correlatos.
SYNONYM_MAP: Dict[str, List[str]] = {
    "carro": ["automotivo", "automotiva", "autopecas", "pecas", "oficina"],
    "veiculo": ["automotivo", "autopecas", "pecas"],
    "auto": ["automotivo", "autopecas", "pecas", "baterias"],
    "oleo": ["lubrificantes", "filtros", "automotivo", "motor"],
    "bateria": ["baterias", "automotivas", "moura", "heliar"],
    "pneu": ["pneus", "rodas", "alinhamento", "balanceamento"],
    "embreagem": ["autopecas", "pecas", "automotivo", "freios", "suspensao"],
    "amortecedor": ["autopecas", "pecas", "suspensao", "automotivo"],
    "freio": ["autopecas", "pecas", "freios", "pastilha"],
    "parafuso": ["parafusos", "ferragens", "fixadores", "ferramentas", "porca", "bucha"],
    "sextavado": ["parafusos", "ferragens", "fixadores", "ferramentas"],
    "furadeira": ["ferramentas", "eletricas", "makita", "bosch", "parafusadeira", "maquinas"],
    "makita": ["ferramentas", "furadeiras", "maquinas", "bosch", "dewalt"],
    "tinta": ["tintas", "impermeabilizantes", "pintura", "coral", "suvinil", "construcao"],
    "pintura": ["tintas", "impermeabilizantes", "construcao"],
    "porcelanato": ["pisos", "revestimentos", "construcao", "acabamentos", "argamassa"],
    "piso": ["pisos", "porcelanato", "revestimentos", "construcao"],
    "cimento": ["construcao", "materiais", "argamassa", "reforma"],
    "cano": ["hidraulica", "tubos", "conexoes", "tigre", "construcao"],
    "torneira": ["hidraulica", "metais", "construcao", "acabamentos", "deca", "docol"],
    "chuveiro": ["hidraulica", "eletricos", "construcao", "lorenzetti", "hydra"],
    "lampada": ["iluminacao", "eletricos", "led", "lustres", "eletrica"],
    "fio": ["eletricos", "eletrica", "cabos", "iluminacao"],
    "celular": ["celulares", "smartphones", "iphone", "assistencia", "acessorios", "informatica"],
    "iphone": ["celulares", "smartphones", "apple", "assistencia"],
    "computador": ["informatica", "computadores", "notebook", "assistencia"],
    "notebook": ["informatica", "computadores", "assistencia"],
    "piscina": ["piscinas", "cloro", "equipamentos", "bombas", "lazer"],
    "camera": ["cameras", "seguranca", "cftv", "alarmes", "monitoramento"],
    "alarme": ["alarmes", "seguranca", "cftv", "cameras", "cerca"],
    "fechadura": ["fechaduras", "ferragens", "chaveiro", "seguranca"],
    "chaveiro": ["chaves", "fechaduras", "seguranca"],
    "colchao": ["colchoes", "camas", "box", "cabeceiras", "sono"],
    "cama": ["camas", "colchoes", "moveis", "cabeceiras"],
    "sofa": ["moveis", "decoracao", "estofados", "tapetes"],
    "cortina": ["cortinas", "persianas", "tapetes", "decoracao"],
    "persiana": ["persianas", "cortinas", "tapetes", "decoracao"],
    "porta": ["esquadrias", "portas", "janelas", "aluminio", "madeira"],
    "janela": ["esquadrias", "janelas", "portas", "aluminio"],
    "oculos": ["oticas", "otica", "lentes", "grau", "armacoes"],
    "lente": ["oticas", "oculos", "lentes", "grau"],
    "racao": ["caes", "gatos", "pet", "agropecuaria", "animais"],
    "cachorro": ["racao", "caes", "pet", "veterinario"],
    "gato": ["racao", "gatos", "pet", "veterinario"],
    "violao": ["instrumentos", "musicais", "musica", "luthieria", "cordas"],
    "guitarra": ["instrumentos", "musicais", "musica", "luthieria"],
    "bicicleta": ["bicicletas", "bike", "ciclismo", "pecas"],
    "bike": ["bicicletas", "ciclismo", "esportes"],
    "whey": ["suplementos", "proteina", "creatina", "vitaminas", "nutrition"],
    "creatina": ["suplementos", "whey", "vitaminas", "nutrition"],
    "remedio": ["farmacia", "manipulacao", "medicamentos", "naturais"],
    "festa": ["festas", "descartaveis", "embalagens", "baloes"],
    "caderno": ["papelaria", "livraria", "escolar", "escritorio"],
    "ar": ["condicionado", "climatizacao", "refrigeracao", "ventiladores"],
    "geladeira": ["eletrodomesticos", "refrigeracao", "assistencia"],
    "fogao": ["eletrodomesticos", "cozinha"]
}

# Palavras de ligação e verbos de intenção que devem ser ignorados como filtro obrigatório
INTENT_STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "com", "em", "no", "na", "nos", "nas",
    "por", "sem", "ou", "e", "a", "o", "as", "os", "um", "uma", "ribeirao", "preto",
    "loja", "lojas", "comercio", "onde", "comprar", "achar", "procurar", "preciso",
    "quero", "tem", "vende", "perto", "mim", "hoje", "agora", "consertar", "conserto",
    "arrumar", "trocar", "troca", "manutencao", "instalacao", "instalar", "fazer"
}


def stem_pt(word: str) -> str:
    """Reduz plural simples em português para melhorar o prefix-match no índice FTS5."""
    w = strip_accents(word.lower().strip())
    if len(w) <= 3:
        return w
    if w.endswith("oes"):
        return w[:-3] + "ao"
    if w.endswith("aes"):
        return w[:-3] + "ao"
    if w.endswith("is") and len(w) > 4:
        return w[:-2]
    if w.endswith("es") and len(w) > 4 and not w.endswith("tes") and not w.endswith("res"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def expand_search_query(raw_query: str):
    """
    Extrai os termos centrais da busca do usuário (removendo verbos como 'consertar', 'comprar')
    e expande com radicais e sinônimos comerciais do SYNONYM_MAP.
    Retorna a tupla (core_words, expanded_words).
    """
    norm_q = strip_accents(raw_query.lower())
    tokens = re.findall(r"[a-z0-9]{2,}", norm_q)
    core_words = [t for t in tokens if t not in INTENT_STOPWORDS]
    if not core_words:
        core_words = [t for t in tokens if len(t) > 1]

    expanded = []
    if any(k in tokens for k in ("consertar", "conserto", "arrumar", "manutencao", "assistencia", "reparo")):
        expanded.extend(["assistencia", "conserto", "manutencao", "oficina"])

    for w in core_words:
        stem = stem_pt(w)
        if w not in expanded:
            expanded.append(w)
        if stem != w and len(stem) >= 3 and stem not in expanded:
            expanded.append(stem)
        for syn_key, syn_list in SYNONYM_MAP.items():
            if w == syn_key or stem == syn_key or (len(stem) >= 4 and syn_key.startswith(stem)):
                for s in syn_list:
                    if s not in expanded:
                        expanded.append(s)

    return core_words, expanded


def format_whatsapp_url(phone: str, store_name: str, query: Optional[str] = None) -> str:
    """Formata o link oficial wa.me com DDD 55 e mensagem contextualizada com o produto buscado."""
    if not phone:
        return ""
    clean_digits = re.sub(r"\D", "", phone)
    if not clean_digits:
        return ""
    if not clean_digits.startswith("55"):
        clean_digits = "55" + clean_digits

    if query and query.strip():
        msg = f"Olá! Vi a loja *{store_name}* no CompraRibeirão e gostaria de saber se vocês têm ou trabalham com *{query.strip()}*."
    else:
        msg = f"Olá! Vi a loja *{store_name}* no CompraRibeirão e gostaria de um atendimento."

    encoded_msg = urllib.parse.quote(msg)
    return f"https://wa.me/{clean_digits}?text={encoded_msg}"


# ==============================================================================
# 3. ROTAS PÚBLICAS DO SITE (Consomem SEMPRE o banco leve PUBLIC_DB_PATH)
# ==============================================================================
@app.get("/api/health")
def health_check():
    """Rota de verificação de saúde para monitoramento do Render."""
    return {"status": "ok", "service": "CompraRibeirão Local Commerce Engine", "version": "2.5.0"}


@app.get("/api/stats")
def get_stats():
    """Retorna os contadores gerais exibidos no topo da plataforma."""
    cached = get_from_cache("stats_v25", ttl_seconds=300)
    if cached:
        return cached

    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM stores")
        total_stores = c.fetchone()[0]

        c.execute("SELECT COUNT(DISTINCT neighborhood) FROM stores WHERE neighborhood IS NOT NULL AND neighborhood != ''")
        total_neighborhoods = c.fetchone()[0]

        try:
            c.execute("SELECT COUNT(*) FROM stores WHERE has_catalog = 1")
            with_catalog = c.fetchone()[0]
        except Exception:
            with_catalog = 0

        try:
            c.execute("SELECT COUNT(*) FROM products")
            total_products = c.fetchone()[0]
        except Exception:
            total_products = 0

        result = {
            "stores_count": total_stores,
            "neighborhoods_count": total_neighborhoods,
            "catalog_stores_count": with_catalog,
            "products_count": total_products,
            "city": "Ribeirão Preto - SP",
            "version": "3.0-local-products"
        }
        set_in_cache("stats_v25", result)
        return result


@app.get("/api/neighborhoods")
def get_neighborhoods():
    """Retorna a lista de bairros padronizados de Ribeirão Preto com contagem de lojas e coordenadas."""
    cached = get_from_cache("neighborhoods_v25", ttl_seconds=600)
    if cached:
        return cached

    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT neighborhood, COUNT(*) as store_count, AVG(latitude) as avg_lat, AVG(longitude) as avg_lng
        FROM stores 
        WHERE neighborhood IS NOT NULL AND neighborhood != ''
        GROUP BY neighborhood
        HAVING store_count >= 1
        ORDER BY store_count DESC, neighborhood ASC
        """)
        rows = [
            {
                "name": r[0],
                "count": r[1],
                "lat": round(r[2], 5) if r[2] else CITY_CENTROID[0],
                "lng": round(r[3], 5) if r[3] else CITY_CENTROID[1]
            }
            for r in c.fetchall()
        ]
        set_in_cache("neighborhoods_v25", rows)
        return rows


@app.get("/api/categories")
def get_categories():
    """Retorna os botões de setores rápidos exibidos abaixo da barra de pesquisa."""
    cached = get_from_cache("categories_list_v25", ttl_seconds=600)
    if cached:
        return cached

    popular_categories = [
        {"id": "baterias", "name": "Baterias", "icon": "fa-car-battery", "query": "bateria automotiva"},
        {"id": "construcao", "name": "Tintas & Pisos", "icon": "fa-trowel-bricks", "query": "tintas pisos porcelanato construcao"},
        {"id": "ferramentas", "name": "Ferramentas & Parafusos", "icon": "fa-wrench", "query": "ferramentas parafusos makita furadeira"},
        {"id": "auto", "name": "Autopeças & Pneus", "icon": "fa-car", "query": "auto pecas pneus oleo"},
        {"id": "hidraulica", "name": "Hidráulica & Elétrica", "icon": "fa-faucet-drip", "query": "hidraulica tubos eletrica iluminacao"},
        {"id": "piscinas", "name": "Piscinas & Lazer", "icon": "fa-water-ladder", "query": "piscina cloro bombas"},
        {"id": "seguranca", "name": "Segurança & CFTV", "icon": "fa-video", "query": "cameras seguranca cftv alarmes fechaduras"},
        {"id": "moveis", "name": "Móveis & Colchões", "icon": "fa-couch", "query": "moveis planejados colchoes cortinas"},
        {"id": "informatica", "name": "Celulares & Informática", "icon": "fa-mobile-screen", "query": "celular iphone computadores informatica"},
        {"id": "oticas", "name": "Óticas & Relógios", "icon": "fa-glasses", "query": "otica oculos lentes"},
        {"id": "pets", "name": "Pet Shop & Rações", "icon": "fa-paw", "query": "racao pet veterinario"},
        {"id": "musica", "name": "Instrumentos & Bikes", "icon": "fa-guitar", "query": "instrumentos musicais violao bicicleta"}
    ]
    set_in_cache("categories_list_v25", popular_categories)
    return popular_categories


@app.get("/api/ads")
def get_ads(position: Optional[str] = None):
    """Retorna os banners patrocinados ativos."""
    cache_key = f"ads_{position}"
    cached = get_from_cache(cache_key, ttl_seconds=600)
    if cached:
        return cached

    with db_transaction(PUBLIC_DB_PATH) as conn:
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


class LeadClickPayload(BaseModel):
    store_id: str
    store_name: Optional[str] = ""
    action_type: str = "whatsapp"  # 'whatsapp', 'gps', 'website', 'map'
    search_query: Optional[str] = ""
    neighborhood: Optional[str] = ""


@app.post("/api/track-lead")
def track_lead(payload: LeadClickPayload):
    """Registra cliques em WhatsApp, Rota GPS e Site para comprovação de retorno (ROI) aos lojistas."""
    try:
        with db_transaction(PUBLIC_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
            INSERT INTO lead_clicks (store_id, store_name, action_type, search_query, neighborhood_filter)
            VALUES (?, ?, ?, ?, ?)
            """, (
                payload.store_id,
                payload.store_name or "",
                payload.action_type,
                payload.search_query or "",
                payload.neighborhood or ""
            ))
        return {"status": "recorded"}
    except Exception as e:
        return {"status": "ignored", "detail": str(e)}


@app.get("/api/leads-report")
def get_leads_report():
    """Relatório de inteligência comercial e conversão de leads por loja e termo buscado."""
    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()
        try:
            top_stores = c.execute("""
                SELECT store_id, store_name, action_type, COUNT(*) as total_clicks
                FROM lead_clicks
                GROUP BY store_id, action_type
                ORDER BY total_clicks DESC
                LIMIT 30
            """).fetchall()
            top_queries = c.execute("""
                SELECT search_query, COUNT(*) as total_searches
                FROM lead_clicks
                WHERE search_query IS NOT NULL AND search_query != ''
                GROUP BY search_query
                ORDER BY total_searches DESC
                LIMIT 20
            """).fetchall()
            return {
                "top_stores": [dict(r) for r in top_stores],
                "top_queries": [dict(r) for r in top_queries]
            }
        except Exception:
            return {"top_stores": [], "top_queries": []}


@app.get("/api/local-search")
def local_search(
    q: Optional[str] = Query(None, description="O que você procura em Ribeirão Preto (ex: makita, embreagem, porcelanato, piscina, bateria)"),
    neighborhood: Optional[str] = Query(None, description="Filtrar ou priorizar bairro em Ribeirão Preto"),
    user_lat: Optional[float] = Query(None, description="Latitude do usuário para ordenação por proximidade"),
    user_lng: Optional[float] = Query(None, description="Longitude do usuário para ordenação por proximidade"),
    include_nearby: bool = Query(True, description="Incluir lojas de bairros vizinhos próximos quando filtrar por bairro"),
    limit: int = 40,
    offset: int = 0
):
    """
    Motor de Busca Híbrido v2.5 para o Comércio Físico de Ribeirão Preto:
    1. Expansão Semântica de Intenção e Sinônimos (Português BR).
    2. FTS5 com pesos BM25 por coluna + Classificação em 3 Camadas (Tier 1 Exato > Tier 2 Parcial > Tier 3 Setor).
    3. Cálculo de Distância Geográfica (Haversine) por GPS do usuário ou centroide do bairro.
    4. Evidências visuais de match ('match_reasons') e filtro dinâmico de produtos de amostra.
    """
    lat_key = f"{user_lat:.3f}_{user_lng:.3f}" if (user_lat is not None and user_lng is not None) else "none"
    cache_key = f"local_search_v25_{q}_{neighborhood}_{lat_key}_{include_nearby}_{limit}_{offset}"
    cached = get_from_cache(cache_key, ttl_seconds=120)
    if cached:
        return cached

    # Determinar ponto de referência geográfico (GPS do usuário OU centroide do bairro selecionado)
    ref_lat, ref_lng = user_lat, user_lng
    clean_neigh = neighborhood.strip() if neighborhood else ""
    if (ref_lat is None or ref_lng is None) and clean_neigh:
        neigh_norm = strip_accents(clean_neigh.lower())
        for k, coords in NEIGHBORHOOD_COORDS.items():
            if strip_accents(k) == neigh_norm or strip_accents(k) in neigh_norm:
                ref_lat, ref_lng = coords[0], coords[1]
                break

    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()

        has_query = bool(q and q.strip())
        core_words, expanded_words = ([], [])

        if has_query:
            core_words, expanded_words = expand_search_query(q.strip())
            fts_terms = []
            for w in expanded_words:
                w_clean = re.sub(r"[^a-zA-Z0-9]", "", w)
                if len(w_clean) >= 2:
                    fts_terms.append(f'"{w_clean}"*')
            fts_query = " OR ".join(dict.fromkeys(fts_terms)) if fts_terms else f'"{q.strip()}"*'

            query_sql = """
            SELECT 
                s.*,
                bm25(stores_search_fts, 12.0, 10.0, 3.0, 9.0, 8.0, 5.0, 2.0) as fts_score
            FROM stores_search_fts
            JOIN stores s ON stores_search_fts.store_id = s.id
            WHERE stores_search_fts MATCH ?
            """
            try:
                c.execute(query_sql, (fts_query,))
                candidate_rows = [dict(r) for r in c.fetchall()]
            except Exception:
                candidate_rows = []
        else:
            if clean_neigh:
                c.execute("SELECT *, 0.0 as fts_score FROM stores WHERE neighborhood = ?", (clean_neigh,))
            else:
                c.execute("SELECT *, 0.0 as fts_score FROM stores")
            candidate_rows = [dict(r) for r in c.fetchall()]

        scored_stores = []
        core_stems = [stem_pt(w) for w in core_words if len(w) >= 2]

        for r in candidate_rows:
            store_neigh = r.get("neighborhood") or "Ribeirão Preto"
            in_selected_neigh = (clean_neigh.lower() == store_neigh.lower()) if clean_neigh else True

            dist_km = None
            lat = r.get("latitude")
            lng = r.get("longitude")
            if ref_lat is not None and ref_lng is not None and lat and lng:
                dist_km = round(haversine_km(ref_lat, ref_lng, float(lat), float(lng)), 1)

            if clean_neigh and not in_selected_neigh:
                if not has_query or not include_nearby or dist_km is None or dist_km > 4.5:
                    continue

            match_tier = 1
            matched_core_count = 0
            match_reasons = []

            name_norm = strip_accents((r.get("name") or "").lower())
            cat_norm = strip_accents((r.get("top_categories") or "") + " " + (r.get("category") or "")).lower()
            brands_norm = strip_accents((r.get("top_brands") or "").lower())
            kw_norm = strip_accents((r.get("keywords") or "").lower())
            sum_norm = strip_accents((r.get("ai_summary") or "").lower())
            full_blob = f"{name_norm} {cat_norm} {brands_norm} {kw_norm} {sum_norm}"

            if has_query and core_stems:
                matched_terms_display = []
                for orig_w, stem in zip(core_words, core_stems):
                    if stem in full_blob or orig_w in full_blob:
                        matched_core_count += 1
                        matched_terms_display.append(orig_w)

                if matched_core_count == len(core_stems):
                    match_tier = 1
                elif matched_core_count > 0:
                    match_tier = 2
                else:
                    match_tier = 3

                for stem in core_stems:
                    if stem in brands_norm:
                        match_reasons.append("Trabalha com a marca pesquisada")
                        break
                if r.get("subcategory") and r.get("subcategory") != "Comércio Local":
                    match_reasons.append(f"Especialidade: {r.get('subcategory')}")
                if matched_terms_display:
                    match_reasons.append(f"Termos identificados: {', '.join(dict.fromkeys(matched_terms_display))}")

            raw_samples = []
            if r.get("sample_products"):
                try:
                    raw_samples = json.loads(r["sample_products"])
                except Exception:
                    raw_samples = []

            if has_query and raw_samples and core_stems:
                matching_samples = []
                other_samples = []
                for sp in raw_samples:
                    sp_title_norm = strip_accents((sp.get("title") or "").lower())
                    if any(st in sp_title_norm for st in core_stems):
                        sp["is_direct_match"] = True
                        matching_samples.append(sp)
                    else:
                        sp["is_direct_match"] = False
                        other_samples.append(sp)
                r["sample_products"] = (matching_samples + other_samples[:8])[:10] if matching_samples else other_samples[:10]
                if matching_samples:
                    match_reasons.insert(0, "Item encontrado no catálogo da loja")
            else:
                r["sample_products"] = raw_samples[:10]

            phone = r.get("whatsapp") or ""
            r["whatsapp_url"] = format_whatsapp_url(phone, r.get("name", "Loja"), q)
            clean_digits = re.sub(r"\D", "", phone)
            num_clean = clean_digits[2:] if clean_digits.startswith("55") else clean_digits
            if len(num_clean) in (10, 11):
                ddd = num_clean[:2]
                num = num_clean[2:]
                r["phone_display"] = f"({ddd}) {num[:5]}-{num[5:]}" if len(num) == 9 else f"({ddd}) {num[:4]}-{num[4:]}"
            else:
                r["phone_display"] = phone or "Consulte via WhatsApp"

            brands_str = r.get("top_brands") or ""
            r["brands_list"] = [b.strip() for b in brands_str.split(",") if b.strip()][:7]

            cats_str = r.get("top_categories") or ""
            r["categories_list"] = [c.strip() for c in cats_str.split(",") if c.strip()][:5]

            r["distance_km"] = dist_km
            r["in_selected_neighborhood"] = in_selected_neigh
            r["match_tier"] = match_tier
            r["match_reasons"] = list(dict.fromkeys(match_reasons))[:3]

            if clean_neigh and in_selected_neigh:
                r["proximity_badge"] = f"📍 No bairro {store_neigh}"
            elif dist_km is not None:
                r["proximity_badge"] = f"🚗 A ~{dist_km:.1f} km ({store_neigh})"
            else:
                r["proximity_badge"] = f"📍 {store_neigh}"

            scored_stores.append(r)

        tier1_count = sum(1 for s in scored_stores if s["match_tier"] == 1)
        if has_query and tier1_count >= 5:
            scored_stores = [s for s in scored_stores if s["match_tier"] in (1, 2)]

        def sort_key(item):
            in_neigh_rank = 0 if item["in_selected_neighborhood"] else 1
            tier_rank = item["match_tier"]
            sponsored_rank = 0 if item.get("is_sponsored") == 1 else 1
            dist_val = item["distance_km"] if item["distance_km"] is not None else 999.0
            fts_val = float(item.get("fts_score") or 0.0)
            catalog_rank = 0 if item.get("has_catalog") == 1 else 1

            if (user_lat is not None and user_lng is not None) or clean_neigh:
                return (in_neigh_rank, tier_rank, sponsored_rank, round(dist_val, 0), fts_val, catalog_rank)
            return (in_neigh_rank, tier_rank, sponsored_rank, fts_val, dist_val, catalog_rank, item.get("name", ""))

        scored_stores.sort(key=sort_key)

        total_found = len(scored_stores)
        paginated_stores = scored_stores[offset : offset + limit]

        result_payload = {
            "query": q,
            "expanded_terms": expanded_words[:10] if has_query else [],
            "neighborhood": neighborhood,
            "total": total_found,
            "count": len(paginated_stores),
            "limit": limit,
            "offset": offset,
            "stores": paginated_stores
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
    """Bridge de compatibilidade para buscas legadas."""
    return local_search(q=q, neighborhood=neighborhood, limit=limit, offset=offset)


@app.get("/api/stores")
def get_stores():
    """Retorna a listagem resumida de todas as lojas públicas."""
    cached = get_from_cache("all_stores_simple_v25", ttl_seconds=600)
    if cached:
        return cached

    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, name, neighborhood, category, macro_category, subcategory, is_sponsored, has_catalog, product_count
        FROM stores
        ORDER BY is_sponsored DESC, name ASC
        """)
        rows = [dict(r) for r in c.fetchall()]
        set_in_cache("all_stores_simple_v25", rows)
        return rows


# ==============================================================================
# 3B. BUSCA DE PRODUTOS DE LOJAS FÍSICAS + CADASTRO POR FOTO (v3.0)
# ==============================================================================
@app.get("/api/products-search")
def products_search(
    q: Optional[str] = Query(None, description="Nome do produto, marca ou categoria"),
    neighborhood: Optional[str] = Query(None, description="Filtrar ou priorizar bairro"),
    user_lat: Optional[float] = Query(None),
    user_lng: Optional[float] = Query(None),
    store_id: Optional[str] = Query(None, description="Filtrar produtos de uma loja específica"),
    limit: int = 36,
    offset: int = 0
):
    """
    Motor de Busca Rápido de Produtos em Lojas Físicas de Ribeirão Preto (< 5ms):
    - Consulta a tabela pública 'products' e o índice FTS5 'products_search_fts'.
    - Prioriza produtos cadastrados por foto ('manual_photo'), match exato das palavras
      buscadas no título do produto, proximidade física (GPS ou bairro) e diversidade de lojas.
    """
    lat_key = f"{user_lat:.3f}_{user_lng:.3f}" if (user_lat is not None and user_lng is not None) else "none"
    cache_key = f"prod_search_v30_{q}_{neighborhood}_{lat_key}_{store_id}_{limit}_{offset}"
    cached = get_from_cache(cache_key, ttl_seconds=120)
    if cached:
        return cached

    ref_lat, ref_lng = user_lat, user_lng
    clean_neigh = neighborhood.strip() if neighborhood else ""
    if (ref_lat is None or ref_lng is None) and clean_neigh:
        neigh_norm = strip_accents(clean_neigh.lower())
        for k, coords in NEIGHBORHOOD_COORDS.items():
            if strip_accents(k) == neigh_norm or strip_accents(k) in neigh_norm:
                ref_lat, ref_lng = coords[0], coords[1]
                break

    has_query = bool(q and q.strip())
    core_words, expanded_words = expand_search_query(q.strip()) if has_query else ([], [])
    core_stems = [stem_pt(w) for w in core_words if len(w) >= 2]

    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()

        if store_id:
            c.execute("SELECT *, 0.0 as fts_score FROM products WHERE store_id = ? LIMIT 300", (store_id,))
            rows = [dict(r) for r in c.fetchall()]
        elif has_query:
            fts_terms = []
            for w in expanded_words:
                w_clean = re.sub(r"[^a-zA-Z0-9]", "", w)
                if len(w_clean) >= 2:
                    fts_terms.append(f'"{w_clean}"*')
            fts_query = " OR ".join(dict.fromkeys(fts_terms)) if fts_terms else f'"{q.strip()}"*'

            sql = """
            SELECT p.*, bm25(products_search_fts, 12.0, 8.0, 5.0, 4.0, 2.0) as fts_score
            FROM products_search_fts
            JOIN products p ON products_search_fts.rowid = p.rowid
            WHERE products_search_fts MATCH ?
            LIMIT 600
            """
            try:
                c.execute(sql, (fts_query,))
                rows = [dict(r) for r in c.fetchall()]
            except Exception:
                rows = []
        else:
            # Sem termo de busca: traz vitrine diversificada de produtos de lojas de Ribeirão
            if clean_neigh:
                c.execute("""
                    SELECT *, 0.0 as fts_score FROM products
                    WHERE neighborhood = ? AND image_url != ''
                    ORDER BY CASE WHEN source_type = 'manual_photo' THEN 0 ELSE 1 END, is_sponsored DESC
                    LIMIT 400
                """, (clean_neigh,))
            else:
                c.execute("""
                    SELECT *, 0.0 as fts_score FROM products
                    WHERE image_url != ''
                    ORDER BY CASE WHEN source_type = 'manual_photo' THEN 0 ELSE 1 END, is_sponsored DESC
                    LIMIT 600
                """)
            rows = [dict(r) for r in c.fetchall()]

        scored_products = []
        per_store_counter: Dict[str, int] = {}

        for p in rows:
            p_Neigh = p.get("neighborhood") or "Ribeirão Preto"
            in_neigh = (clean_neigh.lower() == p_Neigh.lower()) if clean_neigh else True

            dist_km = None
            lat = p.get("latitude")
            lng = p.get("longitude")
            if ref_lat is not None and ref_lng is not None and lat and lng:
                dist_km = round(haversine_km(ref_lat, ref_lng, float(lat), float(lng)), 1)

            if clean_neigh and not in_neigh:
                if dist_km is None or dist_km > 5.0:
                    continue

            title_norm = strip_accents((p.get("title") or "").lower())
            brand_norm = strip_accents((p.get("brand") or "").lower())
            cat_norm = strip_accents((p.get("category") or "").lower())
            blob = f"{title_norm} {brand_norm} {cat_norm}"

            match_tier = 1
            if has_query and core_stems:
                title_matches = sum(1 for st in core_stems if st in title_norm or st in brand_norm)
                blob_matches = sum(1 for st in core_stems if st in blob)
                if title_matches == len(core_stems):
                    match_tier = 1
                elif blob_matches == len(core_stems) or title_matches > 0:
                    match_tier = 2
                else:
                    match_tier = 3

            p["distance_km"] = dist_km
            p["in_selected_neighborhood"] = in_neigh
            p["match_tier"] = match_tier
            p["whatsapp_url"] = format_whatsapp_url(
                p.get("whatsapp") or "",
                p.get("store_name") or "Loja",
                p.get("title") or q
            )
            scored_products.append(p)

        # Se há muitos produtos Tier 1 exatos, descarta ruído Tier 3
        t1_count = sum(1 for item in scored_products if item["match_tier"] == 1)
        if has_query and t1_count >= 6:
            scored_products = [item for item in scored_products if item["match_tier"] in (1, 2)]

        # Ordena priorizando: Bairro selecionado -> Fotos manuais / Tier -> Menor distância -> Score FTS
        def prod_sort_key(item):
            in_neigh_rank = 0 if item["in_selected_neighborhood"] else 1
            manual_rank = 0 if item.get("source_type") == "manual_photo" else 1
            tier_rank = item["match_tier"]
            has_img_rank = 0 if item.get("image_url") else 1
            dist_val = item["distance_km"] if item["distance_km"] is not None else 999.0
            fts_val = float(item.get("fts_score") or 0.0)
            return (in_neigh_rank, tier_rank, manual_rank, has_img_rank, round(dist_val, 0), fts_val)

        scored_products.sort(key=prod_sort_key)

        # Garante diversidade entre lojas na vitrine (evita mostrar 30 itens seguidos da mesma loja)
        diversified = []
        overflow = []
        max_per_store_first_pass = 4 if not has_query else 8
        for item in scored_products:
            sid = item.get("store_id") or ""
            cnt = per_store_counter.get(sid, 0)
            if cnt < max_per_store_first_pass or store_id:
                per_store_counter[sid] = cnt + 1
                diversified.append(item)
            else:
                overflow.append(item)

        final_list = diversified + overflow
        total_found = len(final_list)
        paginated = final_list[offset : offset + limit]

        payload = {
            "query": q,
            "neighborhood": neighborhood,
            "total": total_found,
            "count": len(paginated),
            "products": paginated
        }
        set_in_cache(cache_key, payload)
        return payload


@app.get("/api/store/{store_id}/products")
def get_store_products(store_id: str, q: Optional[str] = None, limit: int = 24):
    """
    Retorna a relação de produtos de uma loja específica para o Carrossel do Mapa
    e para a Ficha da Loja.
    """
    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM stores WHERE id = ?", (store_id,))
        store_row = c.fetchone()
        if not store_row:
            raise HTTPException(status_code=404, detail="Loja não encontrada")
        store = dict(store_row)

        c.execute("""
            SELECT * FROM products
            WHERE store_id = ?
            ORDER BY CASE WHEN source_type = 'manual_photo' THEN 0 WHEN image_url != '' THEN 1 ELSE 2 END, price DESC
            LIMIT ?
        """, (store_id, limit))
        prods = [dict(r) for r in c.fetchall()]

        # Se a busca atual tiver um termo, coloca primeiro os produtos da loja que batem com o termo
        if q and q.strip() and prods:
            stems = [stem_pt(w) for w in expand_search_query(q.strip())[0] if len(w) >= 2]
            if stems:
                prods.sort(key=lambda p: 0 if any(st in strip_accents((p.get("title") or "").lower()) for st in stems) else 1)

        for p in prods:
            p["whatsapp_url"] = format_whatsapp_url(
                store.get("whatsapp") or "",
                store.get("name") or "Loja",
                p.get("title")
            )

        store_whatsapp_url = format_whatsapp_url(
            store.get("whatsapp") or "",
            store.get("name") or "Loja",
            q
        )

        return {
            "store_id": store_id,
            "store_name": store.get("name"),
            "neighborhood": store.get("neighborhood"),
            "address": store.get("address") or "",
            "subcategory": store.get("subcategory") or store.get("macro_category") or "Comércio Local",
            "latitude": store.get("latitude"),
            "longitude": store.get("longitude"),
            "whatsapp": store.get("whatsapp") or "",
            "whatsapp_url": store_whatsapp_url,
            "has_catalog": store.get("has_catalog") or (1 if prods else 0),
            "product_count": store.get("product_count") or len(prods),
            "products": prods
        }


class ManualProductPayload(BaseModel):
    store_id: str  # ID de loja existente ou '__new__' para cadastrar nova loja física sem site
    new_store_name: Optional[str] = ""
    new_store_neighborhood: Optional[str] = ""
    new_store_address: Optional[str] = ""
    new_store_whatsapp: Optional[str] = ""
    new_store_category: Optional[str] = "Comércio Local"
    title: str
    price: Optional[float] = 0.0
    brand: Optional[str] = ""
    category: Optional[str] = "Comércio Local"
    image_data_url: Optional[str] = ""


@app.post("/api/manual-product")
def create_manual_product(payload: ManualProductPayload):
    """
    Cadastra rapidamente um produto fotografado em uma loja física de Ribeirão Preto
    (inclusive lojas sem site que só existem no bairro/Google Maps) e já o indexa
    instantaneamente no motor de busca e no mapa!
    """
    title_clean = (payload.title or "").strip()
    if len(title_clean) < 2:
        raise HTTPException(status_code=400, detail="Informe o nome do produto.")

    store_id = (payload.store_id or "").strip()

    with db_transaction(PUBLIC_DB_PATH) as conn:
        c = conn.cursor()

        # 1. Verifica se é uma loja nova sendo cadastrada na hora ou uma loja existente
        if store_id == "__new__" or not store_id:
            s_name = (payload.new_store_name or "").strip()
            if len(s_name) < 2:
                raise HTTPException(status_code=400, detail="Informe o nome da loja física.")
            slug = re.sub(r"[^\w\s-]", "", strip_accents(s_name.lower()))
            slug = re.sub(r"[\s_-]+", "-", slug).strip("-") or f"loja-{int(time.time())}"
            store_id = slug
            s_neigh = (payload.new_store_neighborhood or "Centro").strip()
            s_addr = (payload.new_store_address or f"{s_neigh}, Ribeirão Preto - SP").strip()
            s_whats = re.sub(r"\D", "", payload.new_store_whatsapp or "")
            if s_whats and not s_whats.startswith("55"):
                s_whats = "55" + s_whats
            s_cat = (payload.new_store_category or payload.category or "Comércio Local").strip()

            # Coordenada aproximada pelo centroide do bairro
            lat, lng = CITY_CENTROID[0], CITY_CENTROID[1]
            neigh_norm = strip_accents(s_neigh.lower())
            for k, coords in NEIGHBORHOOD_COORDS.items():
                if strip_accents(k) == neigh_norm or strip_accents(k) in neigh_norm:
                    lat, lng = coords[0], coords[1]
                    break

            c.execute("""
            INSERT INTO stores (
                id, name, slug, category, macro_category, subcategory, neighborhood, address,
                city, state, whatsapp, website, logo_url, latitude, longitude, is_sponsored,
                has_catalog, product_count, top_categories, top_brands, specialties, keywords,
                ai_summary, sample_products
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Ribeirão Preto', 'SP', ?, '', '', ?, ?, 0, 1, 0, ?, ?, ?, ?, ?, '[]')
            ON CONFLICT(id) DO NOTHING
            """, (
                store_id, s_name, slug, s_cat, s_cat, s_cat, s_neigh, s_addr,
                s_whats, lat, lng, s_cat, payload.brand or "", title_clean,
                f"{s_name.lower()}, {title_clean.lower()}, {s_cat.lower()}",
                f"Loja física localizada no bairro {s_neigh} em Ribeirão Preto."
            ))

        c.execute("SELECT * FROM stores WHERE id = ?", (store_id,))
        store_row = c.fetchone()
        if not store_row:
            raise HTTPException(status_code=404, detail="Loja selecionada não encontrada.")
        store = dict(store_row)

        # 2. Cria e indexa o novo produto fotografado
        prod_id = f"{store_id}_photo_{int(time.time() * 1000)}"
        price_val = float(payload.price or 0.0)
        brand_val = (payload.brand or "").strip()
        cat_val = (payload.category or store.get("subcategory") or "Comércio Local").strip()
        img_val = (payload.image_data_url or "").strip()

        c.execute("""
        INSERT INTO products (
            id, store_id, store_name, neighborhood, whatsapp, latitude, longitude,
            title, price, brand, category, image_url, product_url, source_type, is_sponsored
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'manual_photo', ?)
        """, (
            prod_id, store_id, store["name"], store["neighborhood"], store.get("whatsapp") or "",
            store.get("latitude"), store.get("longitude"), title_clean, price_val,
            brand_val, cat_val, img_val, store.get("is_sponsored") or 0
        ))
        new_rowid = c.lastrowid

        c.execute("""
        INSERT INTO products_search_fts (
            rowid, title, brand, category, store_name, neighborhood
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            new_rowid, title_clean, brand_val, cat_val, store["name"], store["neighborhood"]
        ))

        # 3. Atualiza os produtos de amostra e palavras-chave da própria loja para aparecer no Mapa na hora
        samples = []
        if store.get("sample_products"):
            try:
                samples = json.loads(store["sample_products"])
            except Exception:
                samples = []
        samples.insert(0, {
            "title": title_clean,
            "price": price_val if price_val > 0 else None,
            "url": "",
            "image": img_val if img_val else None
        })
        new_kw = f"{title_clean.lower()}, {brand_val.lower()}, {store.get('keywords') or ''}".strip(", ")

        c.execute("""
        UPDATE stores
        SET has_catalog = 1,
            product_count = COALESCE(product_count, 0) + 1,
            sample_products = ?,
            keywords = ?
        WHERE id = ?
        """, (json.dumps(samples[:16], ensure_ascii=False), new_kw[:2500], store_id))

        c.execute("""
        INSERT INTO stores_search_fts (
            store_id, name, category, neighborhood, top_categories, top_brands, keywords, ai_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_id, store["name"], store.get("category") or "", store.get("neighborhood") or "",
            store.get("top_categories") or "", f"{brand_val} {store.get('top_brands') or ''}",
            title_clean.lower(), store.get("ai_summary") or ""
        ))

    # 4. Se estivermos no PC Local (onde 'compraribeirao.db' existe), salva também no banco bruto permanente!
    if os.path.exists(RAW_DB_PATH):
        try:
            with db_transaction(RAW_DB_PATH) as raw_conn:
                rc = raw_conn.cursor()
                rc.execute("""
                INSERT INTO stores (id, name, slug, category, neighborhood, address, city, state, whatsapp, website, platform)
                VALUES (?, ?, ?, ?, ?, ?, 'Ribeirão Preto', 'SP', ?, ?, 'manual_photo')
                ON CONFLICT(id) DO NOTHING
                """, (
                    store_id, store["name"], store["slug"], store.get("category") or "Comércio Local",
                    store["neighborhood"], store.get("address") or "Ribeirão Preto - SP",
                    store.get("whatsapp") or "", store.get("website") or ""
                ))
                rc.execute("""
                INSERT INTO products (
                    id, store_id, title, description, price, original_price,
                    category, brand, image_url, product_url, in_stock, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', 1, 'manual_photo')
                """, (
                    prod_id, store_id, title_clean, title_clean, price_val, price_val,
                    cat_val, brand_val, img_val
                ))
        except Exception as e:
            print(f"[Aviso] Não foi possível espelhar no banco bruto: {e}")

    clear_all_cache()
    return {
        "status": "ok",
        "product_id": prod_id,
        "store_id": store_id,
        "store_name": store["name"],
        "neighborhood": store["neighborhood"]
    }


# ==============================================================================
# 4. PAINEL DE CONTROLE E MANUTENÇÃO LOCAL (/api/admin/*)
#    Permite rodar Captura, Extração Textual, IA Local, Compilação e Deploy
#    diretamente pela interface web quando rodando no PC do desenvolvedor.
# ==============================================================================
_ADMIN_JOB_STATE: Dict[str, Any] = {
    "running": False,
    "step": None,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "logs": [],
    "process": None
}


class AdminRunStepPayload(BaseModel):
    step: str  # 'discover', 'crawl-text', 'scrap', 'enrich-ai', 'build-kb', 'deploy', 'all'
    query: Optional[str] = None
    force: bool = False
    msg: Optional[str] = "Atualizacao via Painel de Controle CompraRibeirao"


@app.get("/api/admin/status")
def admin_get_status():
    """
    Retorna o diagnóstico completo dos bancos de dados (bruto e público),
    status do Ollama e os logs em tempo real de tarefas de manutenção em execução.
    """
    diag = get_system_diagnostics()
    return {
        "is_local_pc": diag["raw_db_exists"],
        "diagnostics": diag,
        "job": {
            "running": _ADMIN_JOB_STATE["running"],
            "step": _ADMIN_JOB_STATE["step"],
            "started_at": _ADMIN_JOB_STATE["started_at"],
            "finished_at": _ADMIN_JOB_STATE["finished_at"],
            "exit_code": _ADMIN_JOB_STATE["exit_code"],
            "logs": _ADMIN_JOB_STATE["logs"][-120:]  # Últimas 120 linhas de log
        }
    }


@app.post("/api/admin/run-step")
def admin_run_step(payload: AdminRunStepPayload):
    """
    Dispara uma etapa da esteira de manutenção em segundo plano no PC local.
    Bloqueado automaticamente na nuvem (Render) para segurança e proteção de RAM.
    """
    if not os.path.exists(RAW_DB_PATH):
        raise HTTPException(
            status_code=403,
            detail="Operação disponível apenas no PC Local de Desenvolvimento (onde o banco bruto 'compraribeirao.db' e a IA Ollama estão instalados)."
        )

    if _ADMIN_JOB_STATE["running"]:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe uma etapa em execução ('{_ADMIN_JOB_STATE['step']}'). Aguarde finalizar ou interrompa antes de iniciar outra."
        )

    valid_steps = {"discover", "crawl-text", "scrap", "enrich-ai", "build-kb", "deploy", "all"}
    if payload.step not in valid_steps:
        raise HTTPException(status_code=400, detail=f"Etapa inválida: {payload.step}")

    venv_python = os.path.join(ROOT_DIR, "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    cmd = [venv_python, "-u", os.path.join(BACKEND_DIR, "run_pipeline.py"), "--step", payload.step]
    if payload.query and payload.query.strip():
        cmd.extend(["--query", payload.query.strip()])
    if payload.force:
        cmd.append("--force")
    if payload.step == "deploy" and payload.msg:
        cmd.extend(["--msg", payload.msg.strip()])

    def _worker():
        _ADMIN_JOB_STATE["running"] = True
        _ADMIN_JOB_STATE["step"] = payload.step
        _ADMIN_JOB_STATE["started_at"] = time.strftime("%H:%M:%S")
        _ADMIN_JOB_STATE["finished_at"] = None
        _ADMIN_JOB_STATE["exit_code"] = None
        _ADMIN_JOB_STATE["logs"] = [f"[{_ADMIN_JOB_STATE['started_at']}] Iniciando etapa '{payload.step}'..."]

        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                cmd,
                cwd=ROOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env
            )
            _ADMIN_JOB_STATE["process"] = proc

            for line in proc.stdout:
                clean_line = line.rstrip("\r\n")
                if clean_line:
                    _ADMIN_JOB_STATE["logs"].append(clean_line)

            proc.wait()
            _ADMIN_JOB_STATE["exit_code"] = proc.returncode
            _ADMIN_JOB_STATE["finished_at"] = time.strftime("%H:%M:%S")
            _ADMIN_JOB_STATE["logs"].append(
                f"[{_ADMIN_JOB_STATE['finished_at']}] Etapa '{payload.step}' finalizada (código {proc.returncode})."
            )
            # Limpa o cache da API para refletir imediatamente qualquer atualização no banco público
            clear_all_cache()
        except Exception as e:
            _ADMIN_JOB_STATE["exit_code"] = -1
            _ADMIN_JOB_STATE["finished_at"] = time.strftime("%H:%M:%S")
            _ADMIN_JOB_STATE["logs"].append(f"[ERRO] Falha ao executar etapa: {e}")
        finally:
            _ADMIN_JOB_STATE["running"] = False
            _ADMIN_JOB_STATE["process"] = None

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"status": "started", "step": payload.step}


@app.post("/api/admin/stop-job")
def admin_stop_job():
    """Interrompe imediatamente uma tarefa de manutenção em andamento."""
    proc = _ADMIN_JOB_STATE.get("process")
    if proc and _ADMIN_JOB_STATE["running"]:
        try:
            proc.terminate()
            _ADMIN_JOB_STATE["logs"].append("[!] Tarefa interrompida manualmente pelo usuário.")
            _ADMIN_JOB_STATE["running"] = False
            return {"status": "stopped"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return {"status": "no_job_running"}


# ==============================================================================
# 5. SERVIÇO DE ARQUIVOS ESTÁTICOS DO FRONTEND
# ==============================================================================
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "CompraRibeirão API está no ar!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
