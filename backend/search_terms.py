import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_connection

EXPANDED_SECTORS = [
    # Construção, Reforma & Acabamento
    {"term": "materiais de construcao ribeirao preto", "category": "Construção & Reforma"},
    {"term": "tintas impermeabilizantes ribeirao preto", "category": "Tintas & Acabamento"},
    {"term": "pisos porcelanatos azulejos ribeirao preto", "category": "Pisos & Revestimentos"},
    {"term": "materiais eletricos iluminacao ribeirao preto", "category": "Elétrica & Iluminação"},
    {"term": "hidraulica tubos conexoes ribeirao preto", "category": "Hidráulica & Encanamento"},
    {"term": "esquadrias portas janelas aluminio ribeirao preto", "category": "Portas & Janelas"},
    {"term": "lustres luminarias led ribeirao preto", "category": "Iluminação & Lustres"},
    {"term": "produtos para piscina equipamentos ribeirao preto", "category": "Piscinas & Lazer"},

    # Ferramentas, Ferragens & Indústria
    {"term": "ferramentas parafusos ferragens ribeirao preto", "category": "Ferramentas & Indústria"},
    {"term": "ferramentas eletricas furadeiras maquinas ribeirao preto", "category": "Ferramentas Elétricas"},
    {"term": "compressores solda equipamentos industriais ribeirao preto", "category": "Máquinas & Indústria"},
    {"term": "fechaduras cadeados cofres chaves ribeirao preto", "category": "Ferragens & Fechaduras"},

    # Automotivo & Transportes
    {"term": "auto pecas ribeirao preto", "category": "Automotivo & Peças"},
    {"term": "motopeças pecas para moto ribeirao preto", "category": "Motos & Moto Peças"},
    {"term": "baterias automotivas ribeirao preto", "category": "Baterias Automotivas"},
    {"term": "pneus rodas alinhamento ribeirao preto", "category": "Pneus & Rodas"},
    {"term": "acessorios automotivos som insulfilm ribeirao preto", "category": "Acessórios Automotivos"},
    {"term": "oleo automotivo lubrificantes filtros ribeirao preto", "category": "Óleos & Lubrificantes"},

    # Informática, Eletrônicos & Telefonia
    {"term": "informatica computadores pecas ribeirao preto", "category": "Informática & Peças"},
    {"term": "celulares smartphones acessorios ribeirao preto", "category": "Celulares & Telefonia"},
    {"term": "notebooks computadores gamer ribeirao preto", "category": "Notebooks & Gamers"},
    {"term": "cameras seguranca cftv alarmes ribeirao preto", "category": "Segurança Eletrônica"},
    {"term": "audio som eletronicos fones ribeirao preto", "category": "Áudio & Eletrônicos"},

    # Games, Hobbies, Brinquedos & Geek
    {"term": "jogos tabuleiro rpg geek ribeirao preto", "category": "Games, RPG & Hobbies"},
    {"term": "videogames consoles jogos ribeirao preto", "category": "Videogames & Consoles"},
    {"term": "brinquedos jogos infantis ribeirao preto", "category": "Brinquedos & Crianças"},
    {"term": "colecionaveis miniaturas action figures ribeirao preto", "category": "Geek & Colecionáveis"},
    {"term": "artigos para festas descartaveis embalagens ribeirao preto", "category": "Festas & Embalagens"},

    # Instrumentos Musicais & Som
    {"term": "instrumentos musicais som ribeirao preto", "category": "Instrumentos Musicais"},
    {"term": "guitarras violoes baixos pedais ribeirao preto", "category": "Cordas & Instrumentos"},
    {"term": "audio profissional caixas de som mesas ribeirao preto", "category": "Áudio Profissional"},

    # Esportes, Ciclismo & Lazer
    {"term": "bicicletaria bicicletas pecas ribeirao preto", "category": "Bicicletas & Ciclismo"},
    {"term": "artigos esportivos suplementos academia ribeirao preto", "category": "Artigos Esportivos"},
    {"term": "pesca camping tiro esportivo ribeirao preto", "category": "Pesca & Camping"},
    {"term": "artes marciais quimonos luvas ribeirao preto", "category": "Artes Marciais & Lutas"},

    # Pet Shop & Agropecuária
    {"term": "pet shop agropecuaria ribeirao preto", "category": "Pet Shop & Veterinária"},
    {"term": "racao acessorios para caes gatos ribeirao preto", "category": "Rações & Acessórios Pet"},
    {"term": "aquarismo peixes aquarios ribeirao preto", "category": "Aquarismo & Peixes"},

    # Casa, Móveis, Decoração & Utilidades
    {"term": "moveis decoracao planejados ribeirao preto", "category": "Móveis & Decoração"},
    {"term": "colchoes camas box cabeceiras ribeirao preto", "category": "Colchões & Camas"},
    {"term": "utilidades domesticas presentes bazar ribeirao preto", "category": "Utilidades Domésticas"},
    {"term": "eletrodomesticos ar condicionado fogao ribeirao preto", "category": "Eletrodomésticos"},
    {"term": "tapetes cortinas persianas ribeirao preto", "category": "Tapeçaria & Cortinas"},
    {"term": "churrasqueiras acessorios carnes facas ribeirao preto", "category": "Churrasco & Cutelaria"},

    # Saúde, Beleza, Ótica & Vestuário
    {"term": "oticas oculos armacoes lentes ribeirao preto", "category": "Óticas & Acessórios"},
    {"term": "farmacia manipulacao produtos naturais ribeirao preto", "category": "Farmácia & Manipulação"},
    {"term": "suplementos alimentares vitaminas ribeirao preto", "category": "Suplementação & Vitaminas"},
    {"term": "cosmeticos perfumaria maquiagem ribeirao preto", "category": "Beleza & Cosméticos"},
    {"term": "calcados sapatos tenis ribeirao preto", "category": "Calçados & Tênis"},
    {"term": "roupas moda masculina feminina ribeirao preto", "category": "Moda & Vestuário"},
    {"term": "joalheria relogios semijoias ribeirao preto", "category": "Joalheria & Relógios"},

    # Papelaria, Livros & Escritório
    {"term": "papelaria livraria material escolar ribeirao preto", "category": "Papelaria & Livraria"},
    {"term": "moveis para escritorio cadeiras computadores ribeirao preto", "category": "Móveis para Escritório"}
]

def init_search_terms():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS search_terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL,
        active BOOLEAN DEFAULT 1,
        total_discovered INTEGER DEFAULT 0,
        last_run_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    inseridos = 0
    for s in EXPANDED_SECTORS:
        c.execute("""
        INSERT INTO search_terms (term, category, active)
        VALUES (:term, :category, 1)
        ON CONFLICT(term) DO UPDATE SET category = excluded.category
        """, s)
        inseridos += 1
        
    conn.commit()
    conn.close()
    print(f"[✓] Base expandida com sucesso! {inseridos} setores comerciais de Ribeirão Preto cadastrados.")

def list_search_terms():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM search_terms ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_search_term(term: str, category: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO search_terms (term, category, active)
    VALUES (?, ?, 1)
    ON CONFLICT(term) DO UPDATE SET active = 1, category = excluded.category
    """, (term.strip(), category.strip()))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_search_terms()
    terms = list_search_terms()
    print(f"\nTotal atual na base: {len(terms)} setores cadastrados:")
    for i, t in enumerate(terms, 1):
        print(f"  {i:2d}. [{t['category']}] -> {t['term']}")
