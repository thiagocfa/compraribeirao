# 📍 CompraRibeirão (v2.5)

> **Motor de Busca e Inteligência Comercial do Comércio Físico de Ribeirão Preto - SP.**  
> Encontre quais lojas físicas da cidade vendem ou consertam o que você precisa hoje, veja a distância até você no mapa e chame direto no WhatsApp (DDD 16) do balcão.

---

## 📖 Manual Completo de Manutenção e Arquitetura

Toda a documentação técnica, explicação dos dois bancos de dados (`compraribeirao.db` local vs. `compraribeirao_publico.db` na nuvem) e o guia passo a passo de manutenção estão em:

👉 **[DOCUMENTACAO_DO_PROJETO.md](DOCUMENTACAO_DO_PROJETO.md)**

---

## 🚀 Como Operar no Dia a Dia (Windows / 1 Clique)

1. **Ligar o Site Localmente (`http://localhost:8000`):**  
   Dê dois cliques em **`ligar_servidor.bat`**.  
   *(Dica: No rodapé do site local, clique em **"⚙️ Painel de Controle"** para rodar capturas, IA e deploy direto pelo navegador!)*

2. **Abrir o Painel de Controle no Terminal (Captura, IA, Compilação):**  
   Dê dois cliques em **`executar_pipeline.bat`**.

3. **Compilar Banco Leve e Subir para a Nuvem (GitHub / Render):**  
   Dê dois cliques em **`sincronizar_nuvem.bat`**.

---

## 📊 Status Atual da Base (v2.5)

- **Lojas físicas indexadas em Ribeirão Preto:** 710 estabelecimentos
- **Locais mapeados no Google Maps:** 1.037 estabelecimentos
- **Sites com conteúdo textual extraído e analisado por IA (Qwen 2.5 3B):** 580 lojas
- **Produtos de referência extraídos de catálogos locais:** 170.992 itens
- **Bairros padronizados de Ribeirão Preto:** 78 bairros
- **Tamanho do Banco Público na Nuvem (`compraribeirao_publico.db`):** 3,10 MB (respostas em < 3ms)
