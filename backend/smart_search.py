import re
import sqlite3
from typing import List, Dict, Any, Optional
from database import get_connection, db_transaction
from geocoding import get_store_coordinates

# Mapeador semântico de intenções para categorias de comércio local
CATEGORY_INTENTS = [
    {
        "category": "Baterias Automotivas",
        "keywords": ["bateria", "baterias", "heliar", "moura", "cral", "batercar", "acumulador"],
        "icon": "fa-car-battery"
    },
    {
        "category": "Peças Automotivas",
        "keywords": ["oleo", "óleo", "filtro", "freio", "pastilha", "amortecedor", "suspensao", "suspensão", "embreagem", "motor", "escapamento", "palheta", "farol", "parachoque", "radiador", "vela", "correia", "auto peca", "autopeça", "motopeça"],
        "icon": "fa-gears"
    },
    {
        "category": "Pneus & Rodas",
        "keywords": ["pneu", "pneus", "roda", "rodas", "alinhamento", "balanceamento", "aro", "pirelli", "michelin", "goodyear"],
        "icon": "fa-circle-dot"
    },
    {
        "category": "Construção & Reforma",
        "keywords": ["tinta", "tintas", "cimento", "argamassa", "piso", "pisos", "porcelanato", "azulejo", "torneira", "tubo", "chuveiro", "cano", "esquadria", "porta", "janela", "tijolo", "impermeabilizante", "verniz", "gesso"],
        "icon": "fa-trowel-bricks"
    },
    {
        "category": "Elétrica & Iluminação",
        "keywords": ["lampada", "lâmpada", "led", "lustre", "fio", "cabo", "tomada", "disjuntor", "interruptor", "refletor", "luminaria", "luminária"],
        "icon": "fa-lightbulb"
    },
    {
        "category": "Ferramentas & Indústria",
        "keywords": ["ferramenta", "ferramentas", "parafuso", "parafusos", "porca", "arruela", "furadeira", "parafusadeira", "disco", "serra", "lixadeira", "solda", "eletrodo", "compressor", "chave", "alicate", "martelo"],
        "icon": "fa-screwdriver-wrench"
    },
    {
        "category": "Informática & Celulares",
        "keywords": ["computador", "notebook", "ssd", "memoria", "memória", "placa", "gamer", "celular", "smartphone", "iphone", "xiaomi", "samsung", "carregador", "tela", "teclado", "mouse", "monitor", "headset"],
        "icon": "fa-laptop"
    },
    {
        "category": "Games, RPG & Hobbies",
        "keywords": ["jogo", "jogos", "tabuleiro", "boardgame", "dados", "rpg", "magic", "pokemon", "videogame", "playstation", "ps4", "ps5", "xbox", "nintendo", "console", "action figure", "colecionavel", "geek"],
        "icon": "fa-dice-d20"
    },
    {
        "category": "Instrumentos Musicais",
        "keywords": ["violao", "violão", "guitarra", "baixo", "corda", "encordoamento", "pedal", "amplificador", "luthier", "teclado musical", "piano", "bateria musical", "prato", "microfone", "caixa de som"],
        "icon": "fa-guitar"
    },
    {
        "category": "Bicicletas & Ciclismo",
        "keywords": ["bicicleta", "bike", "ciclismo", "camara", "câmara", "pedal", "cambio", "câmbio", "freio a disco", "capacete ciclista", "graxa"],
        "icon": "fa-bicycle"
    },
    {
        "category": "Pet Shop & Veterinária",
        "keywords": ["racao", "ração", "pet", "cachorro", "gato", "filhote", "antipulgas", "bravecto", "simparic", "sache", "sachê", "petisco", "coleira", "areia", "aquario", "aquário", "peixe"],
        "icon": "fa-paw"
    },
    {
        "category": "Suplementação & Esporte",
        "keywords": ["whey", "creatina", "suplemento", "suplementos", "proteina", "proteína", "pre treino", "pré-treino", "bcaa", "termogenico", "academia", "luva boxe", "kimono", "quimono"],
        "icon": "fa-dumbbell"
    },
    {
        "category": "Móveis & Decoração",
        "keywords": ["sofa", "sofá", "mesa", "cadeira", "colchao", "colchão", "cama", "guarda roupa", "armario", "armário", "cortina", "tapete", "persiana"],
        "icon": "fa-couch"
    },
    {
        "category": "Óticas & Acessórios",
        "keywords": ["oculos", "óculos", "armacao", "armação", "lente", "lentes", "grau", "otica", "ótica", "solar"],
        "icon": "fa-glasses"
    }
]

def detect_intent(query: str) -> Optional[Dict[str, Any]]:
    """Detecta a categoria comercial de Ribeirão Preto a partir do termo pesquisado."""
    if not query:
        return None
    
    q_norm = query.lower()
    for cat in CATEGORY_INTENTS:
        for kw in cat["keywords"]:
            # Procura por palavra exata ou início de palavra
            if re.search(r'\b' + re.escape(kw), q_norm):
                return {
                    "category": cat["category"],
                    "icon": cat["icon"],
                    "matched_keyword": kw
                }
    return None

def smart_search_stores(
    q: Optional[str] = None,
    neighborhood: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Motor Híbrido:
    1. Detecta a intenção / categoria do que o usuário quer.
    2. Busca lojas físicas que atendem àquela categoria em Ribeirão Preto.
    3. Busca na base de 170k produtos quais lojas têm os itens reais em catálogo.
    4. Atribui coordenadas geográficas e monta o resultado para o mapa.
    """
    intent = detect_intent(q) if q else None
    detected_category = intent["category"] if intent else None

    with db_transaction() as conn:
        c = conn.cursor()

        # 1. Busca produtos correspondentes via FTS5 para identificar lojas com estoque real
        matching_stores_products: Dict[str, List[Dict[str, Any]]] = {}
        if q and q.strip():
            words = re.findall(r'\w+', q.strip())
            if words:
                fts_query = " ".join([f'"{w}"*' for w in words])
                try:
                    c.execute("""
                    SELECT p.id, p.store_id, p.title, p.price, p.image_url, p.product_url
                    FROM products_fts
                    JOIN products p ON products_fts.product_id = p.id
                    WHERE products_fts MATCH ? AND p.in_stock = 1
                    ORDER BY (p.price > 0) DESC, products_fts.rank ASC
                    LIMIT 200
                    """, (fts_query,))
                    
                    for row in c.fetchall():
                        sid = row["store_id"]
                        if sid not in matching_stores_products:
                            matching_stores_products[sid] = []
                        if len(matching_stores_products[sid]) < 3: # Guarda até 3 produtos de amostra por loja
                            matching_stores_products[sid].append({
                                "title": row["title"],
                                "price": row["price"],
                                "image_url": row["image_url"],
                                "product_url": row["product_url"]
                            })
                except Exception:
                    pass

        # 2. Busca lojas no banco
        where_clauses = ["1=1"]
        params = []

        if neighborhood and neighborhood.strip():
            where_clauses.append("s.neighborhood = ?")
            params.append(neighborhood.strip())

        # Query de lojas
        c.execute(f"""
        SELECT 
            s.id, s.name, s.slug, s.category, s.neighborhood, s.address, 
            s.whatsapp, s.website, s.logo_url, s.is_sponsored,
            COUNT(p.id) as catalog_items_count
        FROM stores s
        LEFT JOIN products p ON s.id = p.store_id
        WHERE {" AND ".join(where_clauses)}
        GROUP BY s.id
        ORDER BY s.is_sponsored DESC, s.name ASC
        """, params)

        raw_stores = [dict(r) for r in c.fetchall()]

    # 3. Pontuação e filtragem inteligente
    ranked_stores = []
    
    for s in raw_stores:
        sid = s["id"]
        s_name = (s["name"] or "").lower()
        s_cat = (s["category"] or "").lower()
        has_products = sid in matching_stores_products
        samples = matching_stores_products.get(sid, [])

        score = 0
        reasons = []

        # Pontuação por produtos reais em estoque
        if has_products:
            score += 100 + (len(samples) * 10)
            reasons.append(f"{len(samples)} produto(s) encontrado(s) no catálogo")

        # Pontuação por categoria detectada
        if detected_category:
            det_low = detected_category.lower()
            if det_low in s_cat or any(w in s_cat for w in det_low.split()):
                score += 50
                reasons.append(f"Especializada em {detected_category}")

        # Pontuação por menção direta no nome da loja ou categoria
        if q:
            q_low = q.lower()
            if q_low in s_name:
                score += 40
                reasons.append("Nome da loja corresponde à pesquisa")
            elif any(word in s_name for word in q_low.split()):
                score += 20
            if q_low in s_cat:
                score += 30
                reasons.append(f"Setor: {s['category']}")

        # Se houver busca e a loja não tem nenhuma relação, desconsidera
        if q and score == 0:
            continue

        # Loja patrocinada ganha bônus
        if s.get("is_sponsored"):
            score += 30

        # Geocodificação das coordenadas
        lat, lng = get_store_coordinates(
            neighborhood=s.get("neighborhood", ""),
            store_name=s.get("name", ""),
            address=s.get("address", "")
        )

        badge = "★ Produtos em Estoque" if has_products else ("Especialista Local" if detected_category else "Loja Física de RP")

        ranked_stores.append({
            "id": s["id"],
            "name": s["name"],
            "category": s["category"] or (detected_category or "Comércio Local"),
            "neighborhood": s["neighborhood"] or "Ribeirão Preto",
            "address": s["address"] or "Ribeirão Preto - SP",
            "whatsapp": s["whatsapp"] or "",
            "website": s["website"] or "",
            "is_sponsored": bool(s["is_sponsored"]),
            "catalog_items_count": s["catalog_items_count"],
            "lat": lat,
            "lng": lng,
            "score": score,
            "badge": badge,
            "reason": reasons[0] if reasons else "Comércio local cadastrado em Ribeirão Preto",
            "sample_products": samples
        })

    # Ordena: Maior score primeiro, patrocinados no topo
    ranked_stores.sort(key=lambda x: (x["is_sponsored"], x["score"]), reverse=True)

    return {
        "query": q,
        "intent_detected": intent,
        "total_stores_found": len(ranked_stores),
        "stores": ranked_stores[:limit]
    }
