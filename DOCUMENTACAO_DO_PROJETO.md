# 📘 CompraRibeirão — Documentação Técnica e Operacional

> **Guia do Comércio Físico Local & Inteligência Comercial de Ribeirão Preto - SP**  
> *Versão:* 2.0.0 • *Atualizado em:* 12/11/2026  
> *Repositório Oficial:* [https://github.com/thiagocfa/compraribeirao](https://github.com/thiagocfa/compraribeirao)  
> *Site no Ar:* [https://compraribeirao.onrender.com/](https://compraribeirao.onrender.com/)

---

## 🎯 1. Visão Geral e Proposta de Valor

O **CompraRibeirão** foi desenhado com foco na maior dor do consumidor de Ribeirão Preto:
> *"Onde em Ribeirão Preto eu encontro uma loja que vende ou conserta o que eu preciso agora, perto do meu bairro, e como falo direto no WhatsApp do comerciante?"*

Diferente de um marketplace tradicional (como Mercado Livre ou Amazon) onde o foco é o SKU unitário com frete demorado, o CompraRibeirão conecta o cidadão diretamente às **710 lojas físicas e especializadas** distribuídas por **148 bairros da cidade**, permitindo:
1. **Entendimento Semântico Local:** Saber quais lojas trabalham com o produto, setor ou marca pesquisada (ex: *baterias Moura/Heliar no Ipiranga, peças Makita na Lagoinha, porcelanatos no Campos Elísios, luthiers no Centro*).
2. **Contato Instantâneo no WhatsApp (DDD 16):** Um clique abre a conversa com o lojista com mensagem pronta já perguntando sobre o item desejado.
3. **Mapa Local Integrado:** Visualização geográfica por bairro sem transformar a interface em um clone genérico do Google Maps — a marca CompraRibeirão e os detalhes do estabelecimento são o foco central.

---

## 🏗️ 2. Arquitetura de Dados em Duas Camadas

Para resolver definitivamente o problema de lentidão e consumo de memória na nuvem gratuita (512 MB de RAM no Render), o sistema opera com **dois bancos de dados especializados**:

```text
┌─────────────────────────────────────────────────────────────────┐
│                    CAMADA DE CAPTURA LOCAL                      │
│                compraribeirao.db (415 MB)                       │
│  - 710 lojas físicas cadastradas                                │
│  - 170.992 produtos brutos capturados via crawlers              │
│  - Usado pelas ferramentas de scraping e descoberta offline     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼ (executado via backend/build_knowledge_base.py em 1.5s)
┌─────────────────────────────────────────────────────────────────┐
│                 KNOWLEDGE BASE PÚBLICO (NUVEM)                  │
│             compraribeirao_publico.db (1.33 MB)                 │
│  - 710 lojas físicas enriquecidas                               │
│  - Top Marcas, Categorias e 40-60 palavras-chave por loja       │
│  - Resumo de especialidades em linguagem natural                │
│  - Coordenadas geográficas (lat/lng) e bairros higienizados     │
│  - Busca Full-Text Search (FTS5) com algoritmo BM25             │
│  - Respostas sub-milimétricas (< 5 ms) na API                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 3. Estrutura de Pastas e Componentes

```text
CompraRibeirao/
│
├── frontend/                          # Interface Web do Usuário
│   └── index.html                     # SPA responsiva (Tailwind CSS, Leaflet Maps, JS)
│
├── backend/                           # Núcleo da Aplicação e Inteligência
│   ├── api.py                         # Servidor FastAPI com rotas /api/local-search, /stats
│   ├── database.py                    # Gerenciador de conexão SQLite com fallback inteligente
│   ├── build_knowledge_base.py        # Sintetizador do banco bruto para o banco público (1.3MB)
│   ├── indexer.py                     # Motor de indexação FTS5
│   ├── search_terms.py                # 60 setores comerciais mapeados para varredura
│   ├── seed_stores.py                 # Lojas âncora iniciais da cidade
│   ├── export_csv.py                  # Exportador de contatos e lojas para prospecção
│   ├── run_pipeline.py                # Executor CLI dos fluxos automatizados
│   ├── discovery_gmaps.py             # Robô de Descoberta no Google Maps (Playwright)
│   └── crawlers/                      # Raspadores de Catálogo (Universal, Tray, VTEX)
│
├── compraribeirao_publico.db          # Banco público leve (1.33 MB) usado em produção
├── compraribeirao.db                  # Banco bruto de mineração (415 MB, versionado via Git LFS)
├── empresas_ribeirao_preto.csv        # Cadastro enriquecido de empresas de RP com coordenadas
├── Dockerfile                         # Containerização para deploy no Render / Hugging Face
├── requirements.txt                   # Dependências Python (FastAPI, Uvicorn, Playwright, etc.)
│
├── ligar_servidor.bat                 # Inicia o servidor local (http://127.0.0.1:8000)
├── executar_pipeline.bat              # Executa mineração de dados
└── sincronizar_nuvem.bat              # Sincroniza código e dados com o GitHub
```

---

## ⚡ 4. Principais Rotas da API (`backend/api.py`)

- `GET /api/stats`: Retorna total de lojas (710), bairros cobertos (103+ higienizados) e status do sistema.
- `GET /api/neighborhoods`: Lista todos os bairros ordenados por concentração de lojas.
- `GET /api/categories`: Categorias e setores comerciais mais buscados da cidade.
- `GET /api/local-search?q=...&neighborhood=...`: Motor de busca FTS5 com BM25 que localiza estabelecimentos físicos por produto, marca, setor ou bairro. Retorna telefone (DDD 16), link direto de WhatsApp, endereço e coordenadas no mapa.
- `GET /api/ads`: Banners patrocinados locais de monetização.

---

## 🚀 5. Como Rodar e Sincronizar

### 1. Iniciar Servidor Local:
Execute `ligar_servidor.bat` ou pelo terminal:
```bash
.\venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```
Acesse no navegador: `http://127.0.0.1:8000/`

### 2. Atualizar o Banco de Inteligência (após novas capturas):
```bash
.\venv\Scripts\python backend/build_knowledge_base.py
```

### 3. Enviar para o GitHub e Atualizar o Render:
Execute `sincronizar_nuvem.bat` ou:
```bash
git add .
git commit -m "feat: atualização"
git push github main
```
O Render detecta o commit na branch `main` e atualiza a aplicação automaticamente em `https://compraribeirao.onrender.com/`.
