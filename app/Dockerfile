# Use slim Python; works great on Apple Silicon with Docker Desktop
FROM python:3.12-slim

# Faster, cleaner installs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (psycopg[binary] needs none, but curl is handy for debug)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# App deps
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app /app/app

# The API listens on 8080 in our charts
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
