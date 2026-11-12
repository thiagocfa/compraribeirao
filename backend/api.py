from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import sys
import sqlite3
import json
import urllib.parse
import math
import unicodedata
from typing import Optional, List, Any, Dict
import re
import time

# Garante que o diretório backend esteja no sys.path
sys.path.append(os.path.dirname(__file__))
from database import get_connection, db_transaction, DB_PATH, PUBLIC_DB_PATH, RAW_DB_PATH
from build_knowledge_base import NEIGHBORHOOD_COORDS, CITY_CENTROID
import search_terms

app = FastAPI(title="CompraRibeirão - Inteligência Comercial Local", version="2.5.0")

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

def get_from_cache(key: str, ttl_seconds: int = 180):
    entry = _RAM_CACHE.get(key)
    if entry and (time.time() - entry["time"] < ttl_seconds):
        return entry["data"]
    return None

def set_in_cache(key: str, data: Any):
    _RAM_CACHE[key] = {"data": data, "time": time.time()}

def strip_accents(text: str) -> str:
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância física real em km entre dois pontos em Ribeirão Preto."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

# Dicionário Semântico de Intenções e Sinônimos do Comércio Físico de Ribeirão Preto
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

INTENT_STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "com", "em", "no", "na", "nos", "nas",
    "por", "sem", "ou", "e", "a", "o", "as", "os", "um", "uma", "ribeirao", "preto",
    "loja", "lojas", "comercio", "onde", "comprar", "achar", "procurar", "preciso",
    "quero", "tem", "vende", "perto", "mim", "hoje", "agora", "consertar", "conserto",
    "arrumar", "trocar", "troca", "manutencao", "instalacao", "instalar", "fazer"
}

def stem_pt(word: str) -> str:
    """Reduz plural simples em português para melhorar prefix-match no FTS5."""
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
    Extrai os termos centrais da busca do usuário e expande com sinônimos comerciais.
    Retorna (core_words, expanded_words).
    """
    norm_q = strip_accents(raw_query.lower())
    tokens = re.findall(r"[a-z0-9]{2,}", norm_q)
    core_words = [t for t in tokens if t not in INTENT_STOPWORDS]
    if not core_words:
        core_words = [t for t in tokens if len(t) > 1]

    expanded = []
    # Se o usuário digitou termos de reparo/conserto, adiciona assistência/oficina como expansão secundária
    if any(k in tokens for k in ("consertar", "conserto", "arrumar", "manutencao", "assistencia", "reparo")):
        expanded.extend(["assistencia", "conserto", "manutencao", "oficina"])

    for w in core_words:
        stem = stem_pt(w)
        if w not in expanded:
            expanded.append(w)
        if stem != w and len(stem) >= 3 and stem not in expanded:
            expanded.append(stem)
        # Busca sinônimos diretos ou pelo radical
        for syn_key, syn_list in SYNONYM_MAP.items():
            if w == syn_key or stem == syn_key or (len(stem) >= 4 and syn_key.startswith(stem)):
                for s in syn_list:
                    if s not in expanded:
                        expanded.append(s)

    return core_words, expanded

def format_whatsapp_url(phone: str, store_name: str, query: Optional[str] = None) -> str:
    """Gera link direto para WhatsApp com mensagem personalizada."""
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

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "CompraRibeirão Local Commerce Engine", "version": "2.5.0"}

@app.get("/api/stats")
def get_stats():
    cached = get_from_cache("stats_v25", ttl_seconds=300)
    if cached:
        return cached

    with db_transaction() as conn:
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
            
        result = {
            "stores_count": total_stores,
            "neighborhoods_count": total_neighborhoods,
            "catalog_stores_count": with_catalog,
            "city": "Ribeirão Preto - SP",
            "version": "2.5-intel"
        }
        set_in_cache("stats_v25", result)
        return result

@app.get("/api/neighborhoods")
def get_neighborhoods():
    cached = get_from_cache("neighborhoods_v25", ttl_seconds=600)
    if cached:
        return cached

    with db_transaction() as conn:
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

class LeadClickPayload(BaseModel):
    store_id: str
    store_name: Optional[str] = ""
    action_type: str = "whatsapp" # 'whatsapp', 'gps', 'website', 'map'
    search_query: Optional[str] = ""
    neighborhood: Optional[str] = ""

@app.post("/api/track-lead")
def track_lead(payload: LeadClickPayload):
    """Registra cliques em WhatsApp, Rota GPS e Site para comprovação de retorno (ROI) aos lojistas."""
    try:
        with db_transaction() as conn:
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
    with db_transaction() as conn:
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
    2. FTS5 com pesos BM25 por coluna + Classificação em 2 Camadas (Match Exato > Match Semântico).
    3. Cálculo de Distância Geográfica (Haversine) por GPS do usuário ou centróide do bairro.
    4. Evidências visuais de match ('Por que indicamos esta loja') e filtro dinâmico de produtos de amostra.
    """
    lat_key = f"{user_lat:.3f}_{user_lng:.3f}" if (user_lat is not None and user_lng is not None) else "none"
    cache_key = f"local_search_v25_{q}_{neighborhood}_{lat_key}_{include_nearby}_{limit}_{offset}"
    cached = get_from_cache(cache_key, ttl_seconds=120)
    if cached:
        return cached

    # Determinar ponto de referência geográfico (GPS do usuário OU centróide do bairro selecionado)
    ref_lat, ref_lng = user_lat, user_lng
    clean_neigh = neighborhood.strip() if neighborhood else ""
    if (ref_lat is None or ref_lng is None) and clean_neigh:
        neigh_norm = strip_accents(clean_neigh.lower())
        for k, coords in NEIGHBORHOOD_COORDS.items():
            if strip_accents(k) == neigh_norm or strip_accents(k) in neigh_norm:
                ref_lat, ref_lng = coords[0], coords[1]
                break

    with db_transaction() as conn:
        c = conn.cursor()

        has_query = bool(q and q.strip())
        core_words, expanded_words = ([], [])

        if has_query:
            core_words, expanded_words = expand_search_query(q.strip())
            # Construir query FTS5 abrangente com OR para resgatar todos os candidatos relevantes
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
            # Sem termo de busca: traz todas as lojas (ou do bairro)
            if clean_neigh:
                c.execute("SELECT *, 0.0 as fts_score FROM stores WHERE neighborhood = ?", (clean_neigh,))
            else:
                c.execute("SELECT *, 0.0 as fts_score FROM stores")
            candidate_rows = [dict(r) for r in c.fetchall()]

        # Processar, pontuar e enriquecer cada loja candidata
        scored_stores = []
        core_stems = [stem_pt(w) for w in core_words if len(w) >= 2]

        for r in candidate_rows:
            store_neigh = r.get("neighborhood") or "Ribeirão Preto"
            in_selected_neigh = ( clean_neigh.lower() == store_neigh.lower() ) if clean_neigh else True

            # Calcular distância física em km se tivermos ponto de referência (GPS ou Bairro)
            dist_km = None
            lat = r.get("latitude")
            lng = r.get("longitude")
            if ref_lat is not None and ref_lng is not None and lat and lng:
                dist_km = round(haversine_km(ref_lat, ref_lng, float(lat), float(lng)), 1)

            # Se o usuário filtrou por bairro:
            if clean_neigh and not in_selected_neigh:
                # Se não tem busca por produto ou se está longe (> 4.5 km), ignora lojas fora do bairro
                if not has_query or not include_nearby or dist_km is None or dist_km > 4.5:
                    continue

            # Avaliar precisão do Match quando há busca textual
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

                # Tier 1: Contém TODAS as palavras-chave principais que o usuário pediu
                # Tier 2: Contém pelo menos uma palavra principal
                # Tier 3: Match por expansão semântica/sinônimo do setor
                if matched_core_count == len(core_stems):
                    match_tier = 1
                elif matched_core_count > 0:
                    match_tier = 2
                else:
                    match_tier = 3

                # Construir evidências claras de por que esta loja responde à busca
                for stem in core_stems:
                    if stem in brands_norm:
                        match_reasons.append(f"Trabalha com a marca pesquisada")
                        break
                if r.get("subcategory") and r.get("subcategory") != "Comércio Local":
                    match_reasons.append(f"Especialidade: {r.get('subcategory')}")
                if matched_terms_display:
                    match_reasons.append(f"Termos identificados: {', '.join(dict.fromkeys(matched_terms_display))}")

            # Filtrar e ordenar produtos de amostra (se a loja tiver catálogo)
            raw_samples = []
            if r.get("sample_products"):
                try:
                    raw_samples = json.loads(r["sample_products"])
                except Exception:
                    raw_samples = []

            if has_query and raw_samples and core_stems:
                # Prioriza amostras cujo título bate com a busca do usuário
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
                # Se encontrou produtos exatos da busca, mostra eles! Caso contrário, mostra até 3 exemplos gerais
                r["sample_products"] = (matching_samples + other_samples[:2])[:3] if matching_samples else other_samples[:3]
                if matching_samples:
                    match_reasons.insert(0, f"Item encontrado no catálogo da loja")
            else:
                r["sample_products"] = raw_samples[:3]

            # Formatar WhatsApp e Telefone
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

            # Listas limpas de marcas e especialidades
            brands_str = r.get("top_brands") or ""
            r["brands_list"] = [b.strip() for b in brands_str.split(",") if b.strip()][:7]

            cats_str = r.get("top_categories") or ""
            r["categories_list"] = [c.strip() for c in cats_str.split(",") if c.strip()][:5]

            r["distance_km"] = dist_km
            r["in_selected_neighborhood"] = in_selected_neigh
            r["match_tier"] = match_tier
            r["match_reasons"] = list(dict.fromkeys(match_reasons))[:3]

            # Badge de proximidade física
            if clean_neigh and in_selected_neigh:
                r["proximity_badge"] = f"📍 No bairro {store_neigh}"
            elif dist_km is not None:
                r["proximity_badge"] = f"🚗 A ~{dist_km:.1f} km ({store_neigh})"
            else:
                r["proximity_badge"] = f"📍 {store_neigh}"

            scored_stores.append(r)

        # Se a busca com match estrito retornou muitos resultados Tier 1, podemos ocultar Tier 3 ruído
        tier1_count = sum(1 for s in scored_stores if s["match_tier"] == 1)
        if has_query and tier1_count >= 5:
            scored_stores = [s for s in scored_stores if s["match_tier"] in (1, 2)]

        # Ordenação Multicritério Inteligente:
        # 1. Se filtrou por bairro: lojas DENTRO do bairro vêm primeiro (in_selected_neighborhood DESC)
        # 2. Match Tier (1 = todas as palavras, 2 = parcial, 3 = sinônimo de setor)
        # 3. Se usuário ativou GPS ("Perto de mim"): ordena por distância física + relevância
        # 4. Patrocinados / Com catálogo / Score BM25
        def sort_key(item):
            in_neigh_rank = 0 if item["in_selected_neighborhood"] else 1
            tier_rank = item["match_tier"]
            sponsored_rank = 0 if item.get("is_sponsored") == 1 else 1
            dist_val = item["distance_km"] if item["distance_km"] is not None else 999.0
            fts_val = float(item.get("fts_score") or 0.0) # negativo no SQLite bm25 (menor = melhor)
            catalog_rank = 0 if item.get("has_catalog") == 1 else 1

            if (user_lat is not None and user_lng is not None) or clean_neigh:
                # Quando GPS ou filtro de bairro está ativo, prioriza estar no bairro -> match_tier -> menor distância física
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
    """Bridge de compatibilidade para buscas."""
    return local_search(q=q, neighborhood=neighborhood, limit=limit, offset=offset)

@app.get("/api/stores")
def get_stores():
    cached = get_from_cache("all_stores_simple_v25", ttl_seconds=600)
    if cached:
        return cached

    with db_transaction() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, name, neighborhood, category, macro_category, subcategory, is_sponsored, has_catalog, product_count
        FROM stores
        ORDER BY is_sponsored DESC, name ASC
        """)
        rows = [dict(r) for r in c.fetchall()]
        set_in_cache("all_stores_simple_v25", rows)
        return rows

# Serve frontend
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
