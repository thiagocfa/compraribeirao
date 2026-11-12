# 📘 CompraRibeirão — Documentação Técnica e Operacional

> **Marketplace Local e Buscador Inteligente de Produtos em Lojas Físicas de Ribeirão Preto - SP**  
> *Versão:* 1.0.0 • *Atualizado em:* 12/11/2026  
> *Repositório Oficial:* [https://github.com/thiagocfa/compraribeirao](https://github.com/thiagocfa/compraribeirao)

---

## 🎯 1. Visão Geral e Proposta de Valor

O **CompraRibeirão** foi criado para resolver a maior dor do consumidor e do comércio de bairro:
> *"Onde tem o produto que eu preciso agora em Ribeirão Preto, quanto custa, em qual bairro fica e como falo direto com a loja pelo WhatsApp?"*

Em vez de depender de entregas de dias de gigantes nacionais (Mercado Livre, Amazon), o morador de Ribeirão Preto pesquisa o item que precisa (ex: *torneira, porcelanato, embreagem de Gol, suplementos, dados de RPG, ferramentas*) e encontra na hora as lojas físicas da cidade com estoque, preço, endereço do bairro e um botão de **WhatsApp direto** com mensagem pré-formatada.

### Pilares Fundamentais:
1. **Custo Zero de APIs:** Não utiliza Google Places API nem serviços pagos de scraping. A captura é 100% automatizada via Playwright e conectores diretos.
2. **Escala Local:** Já conta com mais de **90.000 produtos** indexados e **314 lojas** em **95 bairros** da cidade.
3. **Monetização Nativa:** Espaços para anúncios patrocinados no topo e no feed, além de destaque prioritário para lojas parceiras.
4. **Sincronização Nuvem com 1 Clique:** Código e banco de dados versionados com Git LFS no GitHub e compatíveis com hospedagem em nuvem gratuita 24/7.

---

## 🏗️ 2. Arquitetura do Sistema e Estrutura de Pastas

```text
CompraRibeirao/
│
├── frontend/                          # Interface Web do Usuário
│   └── index.html                     # SPA responsiva (Tailwind CSS, FontAwesome, JS)
│
├── backend/                           # Núcleo da Aplicação e Inteligência
│   ├── api.py                         # Servidor REST FastAPI (rotas de busca, filtros, stats)
│   ├── database.py                    # Gerenciador SQLite WAL, pools e db_transaction
│   ├── indexer.py                     # Motor de indexação FTS5 (Full-Text Search com BM25)
│   ├── search_terms.py                # 60 setores comerciais mapeados para varredura
│   ├── seed_stores.py                 # Lojas âncora iniciais da cidade
│   ├── export_csv.py                  # Exportador de contatos e lojas para prospecção
│   ├── run_pipeline.py                # Executor CLI dos fluxos automatizados
│   │
│   ├── discovery_gmaps.py             # Robô de Descoberta no Google Maps (Playwright)
│   │
│   └── crawlers/                      # Motores de Extração de Catálogo
│       ├── universal_crawler.py       # Identificador de plataforma e ingestão unificada
│       ├── tray_crawler.py            # Raspador assíncrono para lojas na plataforma Tray
│       └── vtex_crawler.py            # Integrador direto para lojas na plataforma VTEX
│
├── compraribeirao.db                  # Banco de Dados SQLite (+90k produtos, FTS5 e WAL)
├── pipeline.py                        # Menu interativo em terminal (Descoberta, Scrap, Web)
├── Dockerfile                         # Containerização para deploy gratuito em nuvem
├── requirements.txt                   # Dependências Python do projeto
│
├── ligar_servidor.bat                 # Inicia o servidor local (http://localhost:8000)
├── executar_pipeline.bat              # Roda o pipeline de extração com 1 clique
└── sincronizar_nuvem.bat              # Sincroniza código e banco de dados com o GitHub
```

---

## ⚙️ 3. O que cada Grande Parte faz (Detalhamento Técnico)

### 3.1. Banco de Dados e Concorrência (`backend/database.py`)
- **Tecnologia:** SQLite 3 nativo em modo **WAL (`Write-Ahead Logging`)**.
- **Segurança de Concorrência:** O modo WAL permite múltiplos leitores simultâneos enquanto um processo escreve, eliminando travamentos.
- **`db_transaction()`:** Gerenciador de contexto Python com **retry automático** (tenta 5 vezes com espera progressiva caso o banco esteja momentaneamente ocupado) e encerramento garantido de conexões (`try/finally`), impedindo o erro de `database is locked`.
- **Tabelas Principais:**
  - `stores`: Cadastro oficial das lojas físicas (nome, bairro, endereço, telefone/WhatsApp, site, plataforma).
  - `products`: Catálogo com título, descrição, preço, categoria, marca, fotos e links.
  - `products_fts`: Tabela virtual FTS5 com tokenizador `unicode61` (ignora acentos no português, pontuações e maiúsculas/minúsculas).
  - `discovered_stores`: Lojas encontradas pelo robô aguardando raspagem de estoque.
  - `search_terms`: Setores comerciais prioritários de Ribeirão Preto.
  - `ad_banners`: Banners e patrocinadores cadastrados.

---

### 3.2. Motor de Descoberta no Google Maps (`backend/discovery_gmaps.py`)
- **Como funciona:** Abre uma instância oculta do navegador Chromium via **Playwright**.
- Navega para `google.com/maps/search/<setor>+ribeirao+preto`.
- Desce a listagem de estabelecimentos, clica individualmente no card de cada loja e extrai:
  - Nome da loja
  - Endereço completo e **bairro identificado**
  - Telefone comercial / WhatsApp
  - Website oficial ou e-commerce
- **Custo:** R$ 0,00 (não utiliza chaves de API do Google Cloud).
- Salva os resultados na tabela `discovered_stores` com status `pending`.

---

### 3.3. Motores de Raspagem e Ingestão de Produtos (`backend/crawlers/`)

#### A. Ingestão Universal (`universal_crawler.py`)
- Lê todas as lojas de `discovered_stores` que possuem site oficial cadastrado.
- Analisa a estrutura do site e detecta automaticamente a plataforma:
  - **VTEX:** Aciona `vtex_crawler.py`.
  - **Tray:** Aciona `tray_crawler.py`.
  - **Loja Integrada:** Faz varredura automática do sitemap `/sitemap/product-1.xml`.
  - **Plataformas Gerais:** Tenta localizar schemas JSON-LD (`@type: Product`) ou OpenGraph tags.
- Grava os produtos extraídos em lote e altera o status da loja para `imported`.

#### B. Conector VTEX (`vtex_crawler.py`)
- Grandes redes locais (como Babá Materiais de Construção e Ri Happy).
- Consulta a árvore de departamentos via API pública e extrai produtos, imagens e preços reais de catálogo sem sobrecarregar o site.

#### C. Conector Tray (`tray_crawler.py`)
- Lojas automotivas, ferramentas e eletrônicos locais (como Raicrom e Dorival Auto Peças).
- Lê o `sitemap.xml`, filtra páginas institucionais e dispara requisições assíncronas paralelas (concorrência de 25 requisições com semáforo), processando mais de 3.000 produtos em menos de 1 minuto.

---

### 3.4. Motor de Indexação e Relevância (`backend/indexer.py`)
- Reconstrói o índice `products_fts`.
- Aplica ordenação híbrida:
  1. **Exatidão no Título:** Se o título do produto começa com o que o usuário digitou, ele ganha prioridade máxima.
  2. **Score BM25:** Algoritmo estatístico que mede a relevância do termo na descrição e marca.
  3. **Lojas Patrocinadas:** Lojas parceiras que pagam mensalidade têm destaque no topo.

---

### 3.5. Servidor e API REST (`backend/api.py`)
Desenvolvido em **FastAPI**, servindo respostas em formato JSON com alta velocidade:
- `GET /api/search`: Busca textual com paginação de 40 em 40 itens e filtros combinados de bairro e loja.
- `GET /api/stats`: Contadores dinâmicos exibidos no cabeçalho.
- `GET /api/neighborhoods`: Lista todos os bairros da cidade que possuem lojas com estoque ativo.
- `GET /api/stores`: Lista de lojas cadastradas com a quantidade de itens de cada uma.
- `GET /api/ads`: Entrega os anúncios patrocinados para exibição.
- `GET /`: Entrega a aplicação web do frontend.

---

### 3.6. Interface do Usuário (`frontend/index.html`)
- Desenvolvida como uma **Single-Page Application (SPA)** leve e responsiva (funciona em smartphones e desktops).
- **Filtros Dinâmicos:** Os selects de bairros e lojas são alimentados pelo banco em tempo real.
- **WhatsApp Integrado:** Cada produto possui botão com link direto para o WhatsApp da loja física responsável, contendo uma mensagem pronta:
  > *"Olá! Vi no CompraRibeirão que vocês têm '[Produto]' por R$ XX,XX. Tem disponível para retirada na loja hoje?"*
- **Painel Administrativo Discreto:** Link `🔒 Painel Admin` no rodapé permitindo disparar varreduras do Google Maps e visualizar empresas capturadas.

---

## 🚀 4. Fluxo Operacional: Como Rodar no Dia a Dia

### Cenário 1: Ligar o Site no Computador
Basta dar dois cliques em:
```text
ligar_servidor.bat
```
Acesse no navegador: **`http://localhost:8000`**

---

### Cenário 2: Adicionar mais Lojas e Produtos (Mineração)
Execute o menu principal dando dois cliques em:
```text
executar_pipeline.bat
```
Ou pelo terminal:
```bash
python pipeline.py
```
O menu exibirá as opções:
1. **[1] Rodar Descoberta no Google Maps:** Você pode digitar um termo específico (ex: *"bicicletaria"*, *"pesca"*, *"ferragens"*) ou pressionar Enter para varrer os setores comerciais cadastrados.
2. **[2] Rodar Scrap dos Produtos:** Lê os sites das lojas encontradas e baixa todo o catálogo de produtos e preços para o banco.
3. **[3] Rodar Pipeline Completo:** Executa a Descoberta + Raspagem + Indexação de uma vez só.

---

### Cenário 3: Sincronizar Tudo com a Nuvem (GitHub)
Sempre que você terminar de rodar uma nova extração ou alterar arquivos:
Dê dois cliques em:
```text
sincronizar_nuvem.bat
```
O script fará o commit de tudo (inclusive do banco de 150 MB via Git LFS) e atualizará o repositório no GitHub automaticamente.

---

## 🌐 5. Como Hospedar Online 24/7 de Graça (Render.com)

Como o projeto possui um **`Dockerfile`** configurado e o código está no GitHub:

1. Acesse **[dashboard.render.com](https://dashboard.render.com)** e faça login com seu GitHub.
2. Clique em **"New +" ➔ "Web Service"**.
3. Selecione o repositório **`thiagocfa/compraribeirao`**.
4. O Render detectará o `Dockerfile` automaticamente. Escolha o plano **Free** ($0/mês).
5. Clique em **"Deploy Web Service"**.
6. Em cerca de 2 minutos você terá uma URL pública permanente (ex: `https://compraribeirao.onrender.com`) com HTTPS, funcionando 24 horas por dia.

---

## 💼 6. Modelo de Negócio e Monetização

O CompraRibeirão possui 3 fontes diretas de receita:

1. **Plano Destaque Lojista (R$ 97 a R$ 197/mês):**
   - A loja ganha o selo `★ Patrocinado`.
   - Seus produtos aparecem sempre no topo das pesquisas quando relevantes.
   - Botão de WhatsApp em destaque e link para o site próprio.
2. **Banners de Publicidade Local (R$ 250 a R$ 500/mês):**
   - Espaço fixo no topo da página (*"Destaque da Semana em Ribeirão"*).
   - Ideal para grandes depósitos, concessionárias e lojas de materiais de construção.
3. **Prospecção de Clientes B2B:**
   - O comando `python backend/export_csv.py` gera um arquivo `empresas_ribeirao_preto.csv` com centenas de telefones comerciais e endereços de lojistas locais prontos para contato da equipe comercial.

---

## 📋 7. Próximos Passos Sugeridos para a Equipe

1. **Expansão de Conectores:** Adicionar suporte específico para extração de lojas que usam **Shopify** e **Nuvemshop**.
2. **Busca Semântica com IA:** Integrar a API do Gemini para entender perguntas naturais (ex: *"onde compro cabo para ligar TV no computador no centro"* ➔ mapear para cabos HDMI no Centro).
3. **Painel do Lojista:** Permitir que donos de lojas locais possam reivindicar sua página, atualizar o WhatsApp e cadastrar promoções manualmente.
