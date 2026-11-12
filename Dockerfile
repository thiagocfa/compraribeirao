FROM python:3.11-slim

WORKDIR /app

# Instala curl para healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código da aplicação e o banco
COPY . .

# Expõe a porta padrão (Hugging Face Spaces usa 7860, Render usa PORT env var)
EXPOSE 7860
EXPOSE 8000

ENV PORT=7860

CMD ["sh", "-c", "uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}"]
