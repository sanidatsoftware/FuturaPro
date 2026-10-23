# MeshCentral (Apache-2.0) per il «Controllo Remoto» di FuturaPro: immagine nostra, con la
# versione bloccata e la configurazione scritta da avvio.js a ogni avvio (vedi lì).
FROM node:22-alpine
WORKDIR /opt/meshcentral
RUN npm install --omit=dev meshcentral@1.3.1 && npm cache clean --force
COPY avvio.js /opt/avvio.js
# Raggiungibile solo da Caddy, nella rete interna di Docker (vedi docker-compose.yml).
EXPOSE 4430
CMD ["node", "/opt/avvio.js"]
