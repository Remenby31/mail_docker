FROM python:3.9-slim

WORKDIR /app

# Installation des dépendances système nécessaires pour psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copie des fichiers requis
COPY requirements.txt .
COPY email_fetcher.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Installation des dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

CMD ["./entrypoint.sh"]