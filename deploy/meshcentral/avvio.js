// Avvio di MeshCentral per FuturaPro: scrive config.json dalle variabili d'ambiente, crea una
// volta sola l'account di servizio con cui FuturaPro lo comanda, poi avvia il server.
//
// MeshCentral risponde in HTTP sulla porta 4430 della rete interna di Docker; Caddy lo pubblica
// in HTTPS sotto https://SERVER/mesh/ (dominio per percorso «mesh»). Gli agenti si collegano a
// wss://SERVER/mesh/agent.ashx e verificano il server con ServerID (il certificato degli agenti,
// nel volume dei dati: va conservato, vedi backup.sh). Nessuno si registra: gli utenti li crea
// FuturaPro e li fa entrare con gettoni a scadenza breve (loginCookieEncryptionKey).
"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { spawn, spawnSync } = require("child_process");

const CARTELLA = process.env.FP_MESH_CARTELLA || "/opt/meshcentral"; // diversa solo nelle prove
const DATI = path.join(CARTELLA, "meshcentral-data");
const MESHCENTRAL = path.join(CARTELLA, "node_modules", "meshcentral");
const indirizzo = process.env.FP_INDIRIZZO;
const chiave = process.env.FP_MESH_CHIAVE || "";
if (!indirizzo) throw new Error("Manca FP_INDIRIZZO.");
if (!/^[0-9a-f]{160}$/.test(chiave)) throw new Error("FP_MESH_CHIAVE deve essere di 160 caratteri esadecimali (vedi installa.sh).");

// Il certificato che gli agenti vedono è quello di Caddy: MeshCentral lo legge da lì (e lo
// rilegge da solo quando Caddy lo rinnova).
const dominio = {
  title: "FuturaPro",
  title2: "Controllo Remoto",
  newAccounts: false,
  certUrl: "https://caddy:443/",
  // Accesso non presidiato, ma chi è davanti allo schermo vede sempre che c'è un tecnico collegato.
  userConsentFlags: { desktopnotify: true, desktopprivacybar: true },
  desktopPrivacyBarText: "Teleassistenza FuturaPro in corso: {0}",
  // Si entra solo dal pannello FuturaPro, con i gettoni che firma dopo la sua verifica in due
  // passaggi; le password degli account sono casuali e non le conosce nessuno. (Il «secondo
  // fattore obbligatorio» di MeshCentral bloccherebbe anche le sessioni aperte con i gettoni.)
  passwordRequirements: { min: 16 },
  agentAllowedIP: process.env.FP_MESH_AGENTI_IP ? process.env.FP_MESH_AGENTI_IP.split(",") : undefined,
};
const configurazione = {
  settings: {
    cert: indirizzo,
    port: 4430,
    aliasPort: 443,
    redirPort: 0,
    mpsPort: 0,
    tlsOffload: true,
    exactPorts: true,
    WANonly: true,
    selfUpdate: false,
    allowLoginToken: true,
    loginCookieEncryptionKey: chiave,
    allowedFramingOrigins: [`https://${indirizzo}`],
    agentIdleTimeout: 150,
  },
  domains: {
    // Il dominio principale c'è sempre ma Caddy non lo pubblica: si usa solo /mesh/.
    "": { title: "FuturaPro", newAccounts: false, certUrl: "https://caddy:443/" },
    mesh: dominio,
  },
};
fs.mkdirSync(DATI, { recursive: true });
fs.writeFileSync(path.join(DATI, "config.json"), JSON.stringify(configurazione, null, 2));

// L'account di servizio (amministratore del dominio «mesh»): la password non serve a nessuno,
// FuturaPro entra con i gettoni. Si crea una volta; il segno resta nel volume dei dati.
const segno = path.join(DATI, "futurapro-account.txt");
if (!fs.existsSync(segno)) {
  const comando = (...argomenti) => {
    const esito = spawnSync("node", [MESHCENTRAL, "--datapath", DATI, ...argomenti], { cwd: CARTELLA, stdio: "inherit", timeout: 300000 });
    if (esito.status !== 0) throw new Error(`MeshCentral ${argomenti[0]} non riuscito.`);
  };
  const password = crypto.randomBytes(24).toString("base64");
  comando("--createaccount", "futurapro", "--pass", password, "--domain", "mesh", "--name", "FuturaPro");
  comando("--adminaccount", "futurapro", "--domain", "mesh");
  fs.writeFileSync(segno, `Account di servizio creato il ${new Date().toISOString()}\n`);
}

// Il server vero e proprio: se si ferma, si ferma anche il container e Docker lo riavvia.
const server = spawn("node", [MESHCENTRAL, "--datapath", DATI], { cwd: CARTELLA, stdio: "inherit" });
for (const segnale of ["SIGTERM", "SIGINT"]) process.on(segnale, () => server.kill(segnale));
server.on("exit", (codice) => process.exit(codice ?? 1));
