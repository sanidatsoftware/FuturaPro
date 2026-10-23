FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FUTURAPRO_MEDIA_ROOT=/dati/media \
    FUTURAPRO_STATIC_ROOT=/dati/static

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Il modello del plugin «Filtro contenuti» (89 MB, controllato con lo SHA-256): un passaggio a sé,
# così non si riscarica a ogni aggiornamento del codice. Se non arriva l'immagine si costruisce lo
# stesso e il pannello segnala il filtro come non disponibile.
COPY plugin/modello/scarica_modello.py plugin/modello/
RUN python plugin/modello/scarica_modello.py

COPY . .
# Un utente senza privilegi; i volumi /dati ereditano la sua proprietà al primo avvio.
RUN useradd --system --uid 1000 --home /app futurapro \
    && mkdir -p /dati/media /dati/static \
    && chown -R futurapro /dati \
    && chmod +x /app/avvio.sh

USER futurapro
EXPOSE 8000
ENTRYPOINT ["/app/avvio.sh"]
