# CompraRibeirão 🚀
> Buscador em tempo real de produtos no comércio físico de Ribeirão Preto - SP.

---

## 🌟 O que está funcionando agora:
1. **Catálogo Real de Ribeirão Preto:**
   - **Babá Materiais de Construção** (Campos Elísios / Av. Saudade) - Extração via API VTEX.
   - **Dorival Auto Peças** (Ipiranga / Rua Mato Grosso) - Extração via Tray E-commerce + Metadados.
   - **Raicrom Ferramentas & Tecnologia** (Alto da Boa Vista / R. Maestro Joaquim Rangel) - Extração via Tray E-commerce.
2. **Motor de Busca Textual Instantâneo (FTS5):**
   - Busca em milissegundos por nome do produto, marca, categoria ou bairro.
3. **Conversão Direta para o Lojista:**
   - Botão **WhatsApp** com mensagem pré-formatada perguntando disponibilidade de retirada imediata na loja física.
   - Link direto para a página do produto no site oficial da loja.
4. **Espaço Publicitário & Monetização Local:**
   - Banner de topo para campanhas patrocinadas locais.
   - Selo *"★ Patrocinado"* que dá prioridade aos parceiros nas buscas.

---

## 💻 Como rodar localmente:

### 1. Iniciar o Servidor Web e API:
```powershell
.\venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload
```
Acesse no navegador: **`http://localhost:8000`**

### 2. Rodar novos crawlers e atualizar catálogo:
```powershell
# Coletar Babá Materiais (VTEX)
.\venv\Scripts\python backend/crawlers/vtex_crawler.py

# Coletar Dorival e Raicrom (Tray)
.\venv\Scripts\python backend/crawlers/tray_crawler.py

# Reconstruir índice de busca FTS5
.\venv\Scripts\python backend/indexer.py
```
