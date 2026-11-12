# 📘 CompraRibeirão (v2.5) — Manual Completo de Arquitetura e Manutenção

> **Motor de Inteligência Comercial e Busca no Comércio Físico de Ribeirão Preto - SP**  
> **Repositório GitHub:** `https://github.com/thiagocfa/compraribeirao`  
> **Produção (Nuvem Render):** `https://compraribeirao.onrender.com/`

---

## 🎯 1. Proposta de Valor e Regra de Ouro do Projeto

O **CompraRibeirão** resolve a dor imediata do morador de Ribeirão Preto:
> *"Preciso comprar ou consertar algo hoje na cidade (ex: bateria automotiva, parafuso sextavado, furadeira Makita, tinta, porcelanato, conserto de celular). Qual loja física perto de mim trabalha com isso e como falo agora no WhatsApp do balcão?"*

* **Não é um e-commerce de carrinho unitário:** O foco é **direcionar o consumidor para a loja física certa no bairro certo**, exibindo:
  1. **Evidências de Match:** Por que aquela loja foi indicada (*marca trabalhada, especialidade ou item encontrado no catálogo*).
  2. **Proximidade Real (GPS / Bairro):** Distância em quilômetros (`Haversine`) a partir do GPS do usuário (*"📍 Perto de Mim"*) ou do bairro selecionado, incluindo lojas especialistas em bairros vizinhos (até 4,5 km).
  3. **Ação Imediata:** Botão direto de **WhatsApp (DDD 16)** com mensagem personalizada e botão **Como Chegar (Rota GPS Google Maps/Waze)**.

---

## 🏗️ 2. Arquitetura em Duas Camadas (PC Local vs. Nuvem)

Para ter **custo zero** de hospedagem e altíssima velocidade no plano gratuito do Render (512 MB de RAM), o sistema separa o processamento pesado da camada pública:

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                CAMADA 1: MINERAÇÃO E IA (100% NO SEU PC LOCAL)            │
│                         compraribeirao.db (~415 MB)                       │
│  • Ignorado no Git (.gitignore) — NUNCA sobe para a nuvem!                │
│  • Tabelas:                                                               │
│    - discovered_stores     (1.037 locais mapeados no Google Maps)         │
│    - stores                (710 lojas físicas únicas de Ribeirão Preto)   │
│    - store_web_content     (Textos extraídos dos sites: título, H1, body) │
│    - store_ai_intelligence (Análise semântica gerada pelo Qwen 2.5 3B)    │
│    - products              (170.992 produtos de lojas com e-commerce)     │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼ Compilado em ~2 segundos por:
                                        backend/build_knowledge_base.py
┌───────────────────────────────────────────────────────────────────────────┐
│                CAMADA 2: PRODUÇÃO ULTRALEVE (GITHUB & RENDER)             │
│                     compraribeirao_publico.db (~3.10 MB)                  │
│  • Único banco enviado ao GitHub e carregado pelo Render.com              │
│  • Contém as 710 lojas enriquecidas, 78 bairros canônicos de RP,          │
│    até 450 termos de estoque por loja, amostras e índice FTS5 BM25.       │
│  • Tempo de resposta da busca: < 3 milissegundos.                         │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 🎛️ 3. Como Usar o Painel de Controle (2 Formas Operacionais)

Você possui **duas formas completas** para operar a captura, rodar a IA, compilar o banco leve e subir para a nuvem:

### Opção A: Painel de Controle Visual pelo Navegador (Web)
1. Inicie o servidor local dando dois cliques em **`ligar_servidor.bat`** (ou opção `9` do `executar_pipeline.bat`).
2. Abra **`http://localhost:8000`** no navegador.
3. Role até o rodapé da página e clique no botão **"⚙️ Painel de Controle"** (ou acesse direto **`http://localhost:8000/?painel=1`**).
4. Dentro do painel visual você verá:
   - **Diagnóstico em Tempo Real** dos dois bancos (`compraribeirao.db` e `compraribeirao_publico.db`) e o status do motor **Ollama (`qwen2.5:3b`)**.
   - **Botões de 1 Clique** para cada uma das 5 etapas + **Botão Mestre ("Rodar Esteira Completa Agora")**.
   - **Console de Execução ao Vivo** mostrando o log linha por linha na tela.

### Opção B: Painel de Controle pelo Windows (`executar_pipeline.bat`)
Dê dois cliques em **`executar_pipeline.bat`** na pasta do projeto. Ele abrirá o menu interativo (`pipeline.py`) com todas as opções numeradas de `1` a `9`:
* `[1]` Ver Diagnóstico Completo do Sistema
* `[2]` **Etapa 1:** Descobrir Novas Lojas no Google Maps
* `[3]` **Etapa 2A:** Extrair Textos Institucionais dos Sites (`web_text_crawler.py`)
* `[4]` **Etapa 2B:** Extrair Produtos de E-commerces (`universal_crawler.py`)
* `[5]` **Etapa 3:** Rodar IA Local Qwen 2.5 via Ollama (`enrich_with_llm.py`)
* `[6]` **Etapa 4:** Compilar Banco Leve da Nuvem (`build_knowledge_base.py`)
* `[7]` **Etapa 5:** Subir Atualização para a Nuvem (`GitHub -> Render`)
* `[8]` **ESTEIRA COMPLETA AUTOMÁTICA** (Textos + IA + Compilar Banco Leve)
* `[9]` Iniciar Servidor Web Local (`http://localhost:8000`)

---

## 🛠️ 4. Passo a Passo de Manutenção (Detalhamento Técnico)

### Etapa 1: Descobrir Novas Lojas no Google Maps
* **Arquivo responsável:** [backend/discovery_gmaps.py](file:///e:/Projetos/CompraRibeirao/backend/discovery_gmaps.py) e [backend/search_terms.py](file:///e:/Projetos/CompraRibeirao/backend/search_terms.py)
* **Como funciona:** Abre um navegador Chromium invisível (Playwright), pesquisa o setor em Ribeirão Preto no Google Maps, rola a lista e extrai Nome, Endereço, Bairro, Telefone e Website, salvando em `discovered_stores`.
* **Como rodar para um novo setor (ex: *"marmoraria"*):**
  * Pelo Painel Web: digite `marmoraria` na Etapa 1 e clique em **Rodar Maps**.
  * Ou via terminal:
    ```powershell
    .\venv\Scripts\python backend/run_pipeline.py --step discover --query "marmoraria ribeirao preto"
    ```
* **Onde adicionar novos setores fixos:** Edite a lista `EXPANDED_SECTORS` dentro de [backend/search_terms.py](file:///e:/Projetos/CompraRibeirao/backend/search_terms.py).

---

### Etapa 2: Capturar Conteúdo Textual e Produtos dos Sites
* **Arquivos responsáveis:**
  * Textos institucionais (SEMPRE salvos para qualquer site): [backend/crawlers/web_text_crawler.py](file:///e:/Projetos/CompraRibeirao/backend/crawlers/web_text_crawler.py)
  * Produtos de e-commerce (Tray, VTEX, Loja Integrada): [backend/crawlers/universal_crawler.py](file:///e:/Projetos/CompraRibeirao/backend/crawlers/universal_crawler.py)
* **Como funciona:**
  * O `web_text_crawler.py` primeiro sincroniza automaticamente qualquer loja nova do Google Maps (`discovered_stores`) para a tabela principal `stores`.
  * Em seguida, visita os sites das lojas e salva permanentemente `page_title`, `meta_description`, `h1_headings`, `h2_headings` e `body_text` na tabela `store_web_content`.
* **Como rodar:**
  * Apenas lojas novas/pendentes:
    ```powershell
    .\venv\Scripts\python backend/run_pipeline.py --step crawl-text
    ```
  * Forçar releitura de todos os sites (`--force`):
    ```powershell
    .\venv\Scripts\python backend/run_pipeline.py --step crawl-text --force
    ```

---

### Etapa 3: Rodar (ou Re-rodar) a IA Local (Qwen 2.5 via Ollama)
* **Arquivo responsável:** [backend/enrich_with_llm.py](file:///e:/Projetos/CompraRibeirao/backend/enrich_with_llm.py)
* **Como funciona:**
  * Lê os textos salvos em `store_web_content` e envia para o modelo local **`qwen2.5:3b`** rodando no **Ollama** (`http://127.0.0.1:11434`).
  * **Auto-Start:** Se o Ollama estiver fechado no Windows, a função `ensure_ollama_running()` inicia o Ollama automaticamente em segundo plano!
  * Salva na tabela `store_ai_intelligence`: `macro_categoria`, `subcategoria`, `especialidades`, `marcas_detectadas`, `resumo_inteligente` e `palavras_chave_busca`.
* **Como rodar:**
  * Analisar apenas lojas novas que ainda não têm IA:
    ```powershell
    .\venv\Scripts\python backend/run_pipeline.py --step enrich-ai
    ```
  * Reanalisar TODAS as lojas do zero (ex: se você mudou o prompt da IA):
    ```powershell
    .\venv\Scripts\python backend/run_pipeline.py --step enrich-ai --force
    ```
* **Como dar manutenção na IA:**
  * Para alterar o prompt ou formato do resumo, edite a função `build_prompt(store)` em [backend/enrich_with_llm.py](file:///e:/Projetos/CompraRibeirao/backend/enrich_with_llm.py).
  * Para trocar o modelo local, altere a constante `MODEL_NAME = "qwen2.5:3b"` no topo de [backend/enrich_with_llm.py](file:///e:/Projetos/CompraRibeirao/backend/enrich_with_llm.py).

---

### Etapa 4: Compilar o Banco Leve Público (`compraribeirao_publico.db`)
* **Arquivo responsável:** [backend/build_knowledge_base.py](file:///e:/Projetos/CompraRibeirao/backend/build_knowledge_base.py)
* **Como funciona:**
  * Lê `compraribeirao.db` (415 MB), unifica dados da IA + produtos + coordenadas GPS, padroniza os 78 bairros de Ribeirão Preto e gera o arquivo ultraleve **`compraribeirao_publico.db` (~3,10 MB)** com índice FTS5.
* **Como rodar:**
  ```powershell
  .\venv\Scripts\python backend/run_pipeline.py --step build-kb
  ```

---

### Etapa 5: Subir para a Nuvem (GitHub $\rightarrow$ Render)
* **Arquivos responsáveis:** `sincronizar_nuvem.bat` ou [backend/run_pipeline.py](file:///e:/Projetos/CompraRibeirao/backend/run_pipeline.py) (`--step deploy`)
* **Como funciona:**
  * Adiciona ao Git **apenas** o banco público leve (`compraribeirao_publico.db`) e os arquivos de código (`backend/`, `frontend/`), cria o commit e faz `git push github main`.
  * O banco pesado (`compraribeirao.db`) está protegido no `.gitignore` para nunca travar seu upload.
  * Assim que o push termina, o **Render.com** detecta o novo commit na branch `main` e atualiza `https://compraribeirao.onrender.com/` automaticamente em cerca de 2 minutos.

---

## 🔍 5. Onde Mexer para Customizações Comuns

| O que você quer fazer | Qual arquivo abrir | Onde editar |
| :--- | :--- | :--- |
| **Adicionar novos sinônimos de busca** (ex: associar uma gíria a um setor) | [backend/api.py](file:///e:/Projetos/CompraRibeirao/backend/api.py) | Dicionário `SYNONYM_MAP` (linhas 86–145) |
| **Mudar os botões de categorias rápidas** abaixo da busca | [backend/api.py](file:///e:/Projetos/CompraRibeirao/backend/api.py) | Função `get_categories()` (`popular_categories`) |
| **Ajustar coordenadas ou nomes de bairros** de Ribeirão Preto | [backend/build_knowledge_base.py](file:///e:/Projetos/CompraRibeirao/backend/build_knowledge_base.py) | Dicionário `NEIGHBORHOOD_COORDS` e função `clean_neighborhood_name()` |
| **Mudar o texto da mensagem automática de WhatsApp** | [backend/api.py](file:///e:/Projetos/CompraRibeirao/backend/api.py) | Função `format_whatsapp_url()` |
| **Alterar visual, cores, cards ou mapa** | [frontend/index.html](file:///e:/Projetos/CompraRibeirao/frontend/index.html) | Função `createStoreCard(store)` e seção HTML do topo |
| **Ver quantos cliques em WhatsApp cada loja recebeu** | Navegador / API | Acesse `http://localhost:8000/api/leads-report` |
| **Colocar uma loja como "Destaque Local" (Patrocinada)** | SQLite (`compraribeirao.db`) | `UPDATE stores SET is_sponsored = 1 WHERE slug = 'nome-da-loja';` e depois rode a Etapa 4 (`build-kb`) |
