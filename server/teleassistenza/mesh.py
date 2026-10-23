"""Il collegamento con MeshCentral, il motore del «Controllo Remoto».

MeshCentral (Apache-2.0) gira come servizio a parte (deploy/meshcentral) ed è pubblicato da
Caddy sotto https://SERVER/mesh/. Sui PC dei negozi c'è il suo agente, che si collega lui al
server: niente porte da aprire nei negozi, funziona in rete locale e da internet.

FuturaPro lo comanda così:

- **Gettoni** (``gettone``): il formato dei «login cookie» di MeshCentral, cifrati AES-256-GCM
  con la chiave condivisa (FUTURAPRO_MESH_CHIAVE, la stessa data a MeshCentral). Valgono pochi
  minuti. Con un gettone il server parla al WebSocket di comando ``control.ashx`` come account di
  servizio «futurapro», e un tecnico apre lo schermo di un PC senza password (il secondo fattore
  lo chiede FuturaPro prima di firmarlo).
- **Un solo gruppo di dispositivi** («Player FuturaPro»): il Controllo Remoto è solo della
  piattaforma (SystemAdministrator e Tecnici), quindi non serve dividere i PC per azienda in
  MeshCentral; l'azienda e il negozio di ogni PC li dice FuturaPro, dal monitor abbinato.
- **Un account MeshCentral per ogni tecnico** (``assicura_account``), così nei registri e nelle
  registrazioni di MeshCentral si vede chi ha fatto cosa.
- **Abbinamento PC ↔ monitor**: lo script di installazione dà all'agente come «tag» l'inizio
  dell'impronta del codice della postazione (vedi ``tag_postazione``); il player manda lo
  stesso codice con il segnale periodico e il server ne conserva l'impronta sul monitor.
"""

import base64
import json
import os
import time
from urllib.parse import quote

from django.conf import settings

DOMINIO = "mesh"
ACCOUNT_SERVIZIO = f"user/{DOMINIO}/futurapro"
NOME_GRUPPO = "Player FuturaPro"
# Consenso del gruppo: 1 = avviso sullo schermo, 64 = barra «collegato»; senza 8, nessuna richiesta
# di permesso a chi è davanti (accesso non presidiato).
CONSENSO = 1 | 64
# Diritti sul gruppo (meshuser.js): 8 controllo remoto, 128 note, 0x100000 dettagli del dispositivo,
# 512 niente terminale (nessuna shell libera: scelta di progetto). I file restano permessi.
DIRITTI_TECNICO = 8 | 128 | 512 | 0x100000
DIRITTI_AMMINISTRATORE = DIRITTI_TECNICO | 0x8000  # anche disinstallare l'agente
# Quanto vale il gettone che apre lo schermo di un PC: va usato subito (la sessione poi dura).
DURATA_GETTONE = 120
ATTESA = 15
LUNGHEZZA_TAG = 32


class MeshNonConfigurato(RuntimeError):
    pass


class MeshErrore(RuntimeError):
    pass


def configurato() -> bool:
    chiave = settings.FUTURAPRO_MESH_CHIAVE or ""
    return bool(settings.FUTURAPRO_MESH_URL and len(chiave) == 160)


def _chiave() -> bytes:
    if not configurato():
        raise MeshNonConfigurato("Controllo Remoto non configurato su questo server (MeshCentral).")
    return bytes.fromhex(settings.FUTURAPRO_MESH_CHIAVE)[:32]


def gettone(dati: dict) -> str:
    """Un «login cookie» di MeshCentral (meshcentral.js, encodeCookie): AES-256-GCM con i primi 32
    byte della chiave, base64 di IV ‖ tag ‖ testo cifrato, con + e / sostituiti da @ e $."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    corpo = json.dumps({**dati, "time": int(time.time())}, separators=(",", ":")).encode()
    iv = os.urandom(12)
    cifrato = AESGCM(_chiave()).encrypt(iv, corpo, None)
    return base64.b64encode(iv + cifrato[-16:] + cifrato[:-16]).decode().replace("+", "@").replace("/", "$")


def tag_postazione(impronta_postazione: str) -> str:
    """Il tag dell'agente per una postazione: l'inizio dell'impronta del suo codice (solo cifre e lettere)."""
    return (impronta_postazione or "")[:LUNGHEZZA_TAG]


def nome_account(utente) -> str:
    return f"fp-{utente.id.hex[:12]}"


class Comando:
    """Una connessione al WebSocket di comando di MeshCentral, come account di servizio.

        with Comando() as mesh:
            mesh.richiedi("meshes")
    """

    def __enter__(self):
        from websockets.sync.client import connect

        base = settings.FUTURAPRO_MESH_URL.rstrip("/")
        indirizzo = base.replace("https://", "wss://").replace("http://", "ws://") + "/control.ashx"
        autorizzazione = gettone({"userid": ACCOUNT_SERVIZIO, "domainid": DOMINIO})
        try:
            # Rete interna di Docker: mai attraverso un proxy (anche se l'ambiente ne indica uno).
            self.ws = connect(f"{indirizzo}?auth={quote(autorizzazione)}", open_timeout=ATTESA, max_size=32 * 1024 * 1024, proxy=None)
        except Exception as errore:
            raise MeshErrore(f"MeshCentral non risponde: {errore}") from errore
        self._numero = 0
        return self

    def __exit__(self, *_):
        self.ws.close()

    def richiedi(self, azione: str, **dati) -> dict:
        """Manda un'azione e aspetta la risposta (stessa «responseid», o la stessa azione per
        quelle che rispondono senza)."""
        self._numero += 1
        risposta_id = f"fp{self._numero}"
        self.ws.send(json.dumps({"action": azione, "responseid": risposta_id, **dati}))
        scadenza = time.monotonic() + ATTESA
        while time.monotonic() < scadenza:
            try:
                messaggio = json.loads(self.ws.recv(timeout=max(0.1, scadenza - time.monotonic())))
            except TimeoutError:
                break
            if messaggio.get("action") == "close":
                raise MeshErrore(f"MeshCentral ha rifiutato l'accesso ({messaggio.get('msg') or messaggio.get('cause')}).")
            if messaggio.get("responseid") == risposta_id or (messaggio.get("action") == azione and "responseid" not in messaggio):
                if messaggio.get("result") not in (None, "ok") and not messaggio.get("success"):
                    if not str(messaggio.get("result", "")).startswith("Added"):
                        raise MeshErrore(f"MeshCentral: {azione} non riuscito ({messaggio.get('result')}).")
                return messaggio
        raise MeshErrore(f"MeshCentral non ha risposto a «{azione}».")


# --- Operazioni ---------------------------------------------------------------------------------


def gruppo(mesh: Comando) -> str:
    """Il gruppo dei PC FuturaPro: si crea la prima volta e se ne ricorda l'identificativo."""
    from .models import ConfigurazioneRemota

    configurazione = ConfigurazioneRemota.attuale()
    gruppi = mesh.richiedi("meshes").get("meshes") or []
    if configurazione.gruppo and any(g.get("_id") == configurazione.gruppo for g in gruppi):
        return configurazione.gruppo
    esistente = next((g["_id"] for g in gruppi if g.get("name") == NOME_GRUPPO), None)
    if esistente is None:
        esistente = mesh.richiedi(
            "createmesh", meshname=NOME_GRUPPO, meshtype=2, desc="I PC dei monitor e dei totem FuturaPro.",
            consent=CONSENSO, flags=0,
        )["meshid"]
    configurazione.gruppo = esistente
    configurazione.save()
    return esistente


def dispositivi(mesh: Comando, id_gruppo: str) -> list[dict]:
    """I PC del gruppo, con lo stato del collegamento."""
    nodi = (mesh.richiedi("nodes", meshid=id_gruppo).get("nodes") or {}).get(id_gruppo, [])
    risultato = []
    for nodo in nodi:
        agente = nodo.get("agent") or {}
        risultato.append({
            "id": nodo.get("_id", ""),
            "nome": nodo.get("name", ""),
            "host": nodo.get("rname") or nodo.get("host") or "",
            "in_linea": bool((nodo.get("conn") or 0) & 1),
            "sistema": nodo.get("osdesc", ""),
            "ip": nodo.get("ip", ""),
            "tag": (agente.get("tag") or "").strip(),
            "ultimo_contatto": nodo.get("lastconnect"),
        })
    return risultato


def informazioni(mesh: Comando, nodo: str) -> dict:
    """L'inventario hardware di un PC (quello che l'agente ha raccolto), in forma ridotta."""
    dati = mesh.richiedi("getsysinfo", nodeid=nodo)
    if dati.get("noinfo"):
        return {}
    hardware = dati.get("hardware") or {}
    windows = hardware.get("windows") or {}
    identificazione = hardware.get("identifiers") or {}
    sistema = (windows.get("osinfo") or {})
    dischi = [
        {"unita": d.get("Caption", ""), "totale": d.get("Size"), "libero": d.get("FreeSpace")}
        for d in (windows.get("volumes") or {}).values() if isinstance(d, dict)
    ] if isinstance(windows.get("volumes"), dict) else []
    return {
        "produttore": identificazione.get("board_vendor") or identificazione.get("product_vendor", ""),
        "modello": identificazione.get("product_name") or identificazione.get("board_name", ""),
        "processore": ", ".join(identificazione.get("cpu_name", []) if isinstance(identificazione.get("cpu_name"), list) else [identificazione.get("cpu_name", "")]).strip(", "),
        "sistema": sistema.get("Caption", ""),
        "versione": sistema.get("Version", ""),
        "memoria": sum(int(m.get("Capacity", 0) or 0) for m in (windows.get("memory") or []) if isinstance(m, dict)) or None,
        "dischi": dischi,
    }


def assicura_account(mesh: Comando, utente, id_gruppo: str) -> str:
    """L'account MeshCentral del tecnico, con i suoi diritti sul gruppo: si crea la prima volta."""
    from .models import AccountRemoto

    nome = nome_account(utente)
    account, nuovo = AccountRemoto.objects.get_or_create(utente=utente, defaults={"nome": nome})
    diritti = DIRITTI_AMMINISTRATORE if utente.ruolo == "admin_assoluto" else DIRITTI_TECNICO
    if nuovo or account.gruppo != id_gruppo or account.diritti != diritti:
        if nuovo:
            # La password non la sa nessuno e non serve: si entra solo con i gettoni di FuturaPro.
            try:
                mesh.richiedi("adduser", username=nome, realname=utente.get_full_name() or utente.username, siteadmin=0, randomPassword=True)
            except MeshErrore as errore:
                if "exist" not in str(errore).lower():
                    raise
        mesh.richiedi("addmeshuser", meshid=id_gruppo, usernames=[nome], meshadmin=diritti)
        account.gruppo, account.diritti = id_gruppo, diritti
        account.save()
    return f"user/{DOMINIO}/{nome}"


def indirizzo_schermo(id_account: str, nodo: str) -> str:
    """L'indirizzo che apre direttamente lo schermo remoto di un PC, già entrati come il tecnico."""
    accesso = gettone({"u": id_account, "a": 3, "expire": max(1, DURATA_GETTONE // 60)})
    nodo_breve = nodo.split("/")[-1]
    base = settings.FUTURAPRO_MESH_PUBBLICO.rstrip("/") + "/"
    return f"{base}?login={quote(accesso)}&gotonode={quote(nodo_breve)}&viewmode=11&hide=31"


def indirizzo_console(id_account: str) -> str:
    """La console completa di MeshCentral, già entrati (solo per il SystemAdministrator)."""
    accesso = gettone({"u": id_account, "a": 3, "expire": max(1, DURATA_GETTONE // 60)})
    return settings.FUTURAPRO_MESH_PUBBLICO.rstrip("/") + f"/?login={quote(accesso)}"


def indirizzo_agente(id_gruppo: str, tag: str) -> str:
    """Il programma di installazione dell'agente per Windows x64, già legato al gruppo e alla postazione."""
    base = settings.FUTURAPRO_MESH_PUBBLICO.rstrip("/") + "/"
    return f"{base}meshagents?id=4&meshid={quote(id_gruppo.split('/')[-1])}&installflags=2&tag={quote(tag)}"
