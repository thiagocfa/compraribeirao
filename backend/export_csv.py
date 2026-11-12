import sqlite3
import csv
import os

def export_to_csv():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "compraribeirao.db")
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "empresas_ribeirao_preto.csv")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
    SELECT 
        id, name, category, neighborhood, address, phone, website, rating, maps_url, query_used, discovered_at
    FROM discovered_stores
    ORDER BY neighborhood ASC, name ASC
    """)
    rows = c.fetchall()
    
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "ID", "Nome da Empresa", "Setor/Categoria", "Bairro", "Endereço Completo", 
            "Telefone/WhatsApp", "Website Oficial", "Avaliação Google", "Link Google Maps", "Termo de Busca Usado", "Data Descoberta"
        ])
        for r in rows:
            writer.writerow(r)
            
    conn.close()
    print(f"[✓] Planilha exportada com sucesso: {csv_path}")
    print(f"[i] Total de {len(rows)} empresas de Ribeirão Preto exportadas!")

if __name__ == "__main__":
    export_to_csv()
