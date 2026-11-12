# 🛒 CompraRibeirão

> **Buscador em tempo real de produtos no comércio físico de Ribeirão Preto - SP.**  
> Encontre onde tem estoque agora nas lojas físicas da cidade sem precisar ligar ou sair de casa, com contato direto por WhatsApp.

---

## 📖 Documentação Completa do Projeto

Para entender toda a arquitetura, o que cada script faz, o fluxo operacional passo a passo e o modelo de negócio, consulte o documento detalhado:

👉 **[DOCUMENTACAO_DO_PROJETO.md](DOCUMENTACAO_DO_PROJETO.md)**

---

## ⚡ Status Atual do Catálogo

- **Produtos ativos cadastrados:** +90.000 produtos
- **Lojas físicas no catálogo:** 314 lojas
- **Bairros mapeados:** 95 bairros de Ribeirão Preto
- **Estabelecimentos comerciais descobertos no Google Maps:** +1.000 lojas

---

## 🚀 Como Iniciar com 1 Clique (Windows)

1. **Ligar o Servidor do Site:**  
   Dê dois cliques no arquivo `ligar_servidor.bat`  
   Acesse no navegador: **`http://localhost:8000`**

2. **Minerar Lojas e Produtos:**  
   Dê dois cliques no arquivo `executar_pipeline.bat` (ou execute `python pipeline.py`)

3. **Sincronizar com o GitHub:**  
   Dê dois cliques no arquivo `sincronizar_nuvem.bat`

---

## 🌐 Deploy na Nuvem (Render.com)

O projeto possui um `Dockerfile` pronto para execução contínua gratuita no [Render.com](https://render.com). Conecte este repositório no Render como **Web Service** para ter o site rodando 24/7 com link público próprio.
