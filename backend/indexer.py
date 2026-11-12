from database import get_connection

def rebuild_index():
    conn = get_connection()
    cursor = conn.cursor()

    print("[*] Reconstruindo índice de busca textual FTS5...")
    cursor.execute("DELETE FROM products_fts")

    cursor.execute("""
    INSERT INTO products_fts (product_id, title, brand, category, description, store_name, neighborhood)
    SELECT 
        p.id,
        p.title,
        COALESCE(p.brand, ''),
        COALESCE(p.category, ''),
        COALESCE(p.description, ''),
        s.name,
        s.neighborhood
    FROM products p
    JOIN stores s ON p.store_id = s.id
    WHERE p.in_stock = 1
    """)

    count = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"[✓] Índice FTS5 atualizado com {count} produtos ativos!")

def seed_sample_ads():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ad_banners")

    ads = [
        {
            "title": "Tintas e Acabamento com Entrega Rápida em Ribeirão",
            "sponsor_name": "Babá Materiais de Construção",
            "image_url": "https://images.unsplash.com/photo-1589939705384-5185137a7f0f?w=1200&auto=format&fit=crop&q=80",
            "target_url": "https://www.babamateriais.com.br",
            "position": "top_banner"
        },
        {
            "title": "Peças e Filtros para seu Carro no Ipiranga",
            "sponsor_name": "Dorival Auto Peças",
            "image_url": "https://images.unsplash.com/photo-1486006920555-c77dce18193b?w=1200&auto=format&fit=crop&q=80",
            "target_url": "https://www.dorivalautopecas.com.br",
            "position": "search_inline"
        }
    ]

    for ad in ads:
        cursor.execute("""
        INSERT INTO ad_banners (title, sponsor_name, image_url, target_url, position)
        VALUES (:title, :sponsor_name, :image_url, :target_url, :position)
        """, ad)

    conn.commit()
    conn.close()
    print("[✓] Espaços publicitários de demonstração configurados!")

if __name__ == "__main__":
    rebuild_index()
    seed_sample_ads()
