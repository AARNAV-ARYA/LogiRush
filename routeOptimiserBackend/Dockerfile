# Backend container for the NER Logistics Intelligence Platform.
#
# Runs the existing Flask app under gunicorn (a production WSGI server) rather than the
# Flask development server, which is single-threaded and explicitly not for production use.

FROM python:3.11-slim

# Build deps for scientific wheels; removed in the same layer to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so Docker caches this layer across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Train and persist the disaster-prediction models at build time so the first request
# doesn't pay the training cost (and so a read-only filesystem at runtime is fine).
RUN python -c "from src.modeling.disaster_prediction import RandomForestDisasterPredictor; RandomForestDisasterPredictor()" || true

ENV PYTHONUNBUFFERED=1 \
    PORT=5001

EXPOSE 5001

# --timeout 120: the original cross-border /api/find-routes endpoint rebuilds the global
# graph per request and can take ~15s; the default 30s timeout is too tight under load.
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 main:app
