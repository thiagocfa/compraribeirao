from database import get_connection

STORES = [
    {
        "id": "baba-materiais",
        "name": "Babá Materiais de Construção",
        "slug": "baba-materiais",
        "category": "Construção & Reforma",
        "neighborhood": "Campos Elísios",
        "address": "Av. Saudade, 1260 - Campos Elísios, Ribeirão Preto - SP",
        "city": "Ribeirão Preto",
        "state": "SP",
        "whatsapp": "5516992231607",
        "website": "https://www.babamateriais.com.br",
        "logo_url": "https://www.babamateriais.com.br/arquivos/logo.png",
        "platform": "vtex",
        "is_sponsored": 1
    },
    {
        "id": "dorival-autopecas",
        "name": "Dorival Auto Peças",
        "slug": "dorival-autopecas",
        "category": "Peças Automotivas",
        "neighborhood": "Ipiranga",
        "address": "Rua Mato Grosso, 370 - Ipiranga, Ribeirão Preto - SP",
        "city": "Ribeirão Preto",
        "state": "SP",
        "whatsapp": "551639636414",
        "website": "https://www.dorivalautopecas.com.br",
        "logo_url": "https://images.tcdn.com.br/img/img_prod/1232696/1691498357_logo_dorival.png",
        "platform": "tray",
        "is_sponsored": 0
    },
    {
        "id": "raicrom",
        "name": "Raicrom Ferramentas & Fixadores",
        "slug": "raicrom",
        "category": "Ferramentas & Indústria",
        "neighborhood": "Alto da Boa Vista",
        "address": "R. Maestro Joaquim Rangel, 849 - Alto da Boa Vista, Ribeirão Preto - SP",
        "city": "Ribeirão Preto",
        "state": "SP",
        "whatsapp": "551639656742",
        "website": "https://www.raicrom.com.br",
        "logo_url": "https://images.tcdn.com.br/img/img_prod/1077127/logo_raicrom.png",
        "platform": "tray",
        "is_sponsored": 0
    }
]

def seed():
    conn = get_connection()
    cursor = conn.cursor()
    for s in STORES:
        cursor.execute("""
        INSERT INTO stores (id, name, slug, category, neighborhood, address, city, state, whatsapp, website, logo_url, platform, is_sponsored)
        VALUES (:id, :name, :slug, :category, :neighborhood, :address, :city, :state, :whatsapp, :website, :logo_url, :platform, :is_sponsored)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            neighborhood = excluded.neighborhood,
            address = excluded.address,
            whatsapp = excluded.whatsapp,
            website = excluded.website,
            platform = excluded.platform,
            is_sponsored = excluded.is_sponsored
        """, s)
    conn.commit()
    conn.close()
    print(f"{len(STORES)} lojas cadastradas/atualizadas com sucesso!")

if __name__ == "__main__":
    seed()
