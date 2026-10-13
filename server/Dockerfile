FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FUTURAPRO_MEDIA_ROOT=/dati/media \
    FUTURAPRO_STATIC_ROOT=/dati/static

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Un utente senza privilegi; i volumi /dati ereditano la sua proprietà al primo avvio.
RUN useradd --system --uid 1000 --home /app futurapro \
    && mkdir -p /dati/media /dati/static \
    && chown -R futurapro /dati \
    && chmod +x /app/avvio.sh

USER futurapro
EXPOSE 8000
ENTRYPOINT ["/app/avvio.sh"]
