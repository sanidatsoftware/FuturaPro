#!/usr/bin/env python3
"""
Installazione automatica della Prima Nota nel portale TOCAL.

Uso (dalla cartella estratta dallo zip):   sudo python3 installa.py
Opzioni:  --portale /opt/tocal   cartella del portale (predefinita /opt/tocal)
          --senza-baserow        non crea la tabella Baserow (si indica l'id a mano)
          --senza-cron           non aggiunge l'importazione serale al crontab
          --solo-file            copia e modifica i file, senza pip/migrate (per prove)

Prima di toccare qualunque cosa salva una copia in <portale>/backup_primanota_<data_ora>/.
Se il controllo finale del portale fallisce, rimette a posto i file da quella copia.
Si può rilanciare: le modifiche già fatte vengono riconosciute e non ripetute.
"""

import argparse
import getpass
import pwd
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

QUI = Path(__file__).resolve().parent
NOME_TABELLA = "Prima Nota Scansioni"
CAMPO_MENU = "Menu_PrimaNota"
MARCATORE_CRON = "# primanota: importazione SysSpy"

CARD_MENU = """        {% primanota_visibile utente as show_primanota %}
        {% if show_primanota %}
        <a class="module-card" href="/primanota/">
            <div class="icon">🧾</div>
            <h2>Prima Nota</h2>
            <p>Scansioni chiusure fiscali, POS, resi, abortite e versamenti, con i file scontrini delle casse.</p>
        </a>
        {% endif %}

"""


def titolo(testo):
    print(f"\n=== {testo}")


def ok(testo):
    print(f"  ✓ {testo}")


def avviso(testo):
    print(f"  ! {testo}")


def errore(testo):
    print(f"\n  ✗ {testo}\n")
    sys.exit(1)


# ---------------------------------------------------------------- copia di sicurezza

class Backup:
    def __init__(self, portale):
        self.portale = portale
        self.cartella = portale / f"backup_primanota_{datetime.now():%Y%m%d_%H%M%S}"
        self.salvati = []

    def salva(self, percorso):
        percorso = Path(percorso)
        if not percorso.exists():
            return
        dest = self.cartella / percorso.relative_to(self.portale)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if percorso.is_dir():
            shutil.copytree(percorso, dest, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(percorso, dest)
        self.salvati.append(percorso)

    def ripristina(self):
        for percorso in self.salvati:
            origine = self.cartella / percorso.relative_to(self.portale)
            if origine.is_dir():
                if percorso.exists():
                    shutil.rmtree(percorso)
                shutil.copytree(origine, percorso)
            else:
                shutil.copy2(origine, percorso)
            print(f"  ripristinato {percorso}")


# ---------------------------------------------------------------- modifiche ai file

def modifica_settings(testo, table_id=None, archivio=None, campo_menu=None):
    if not re.search(r"""['"]primanota['"]""", testo):
        m = re.search(r"INSTALLED_APPS\s*=\s*\[(.*?)\n\]", testo, re.S)
        if not m:
            raise ValueError("INSTALLED_APPS non trovato in settings.py")
        testo = testo[:m.end() - 1] + '    "primanota",\n' + testo[m.end() - 1:]
    if "BASEROW_PRIMANOTA_TABLE_ID" not in testo:
        testo = testo.rstrip("\n") + (
            "\n\n# Prima Nota\n"
            "BASEROW_PRIMANOTA_TABLE_ID = None\n"
            f'PRIMANOTA_ARCHIVIO_DIR = "{archivio}"\n')
    if "BASEROW_UTENTE_MENU_PRIMANOTA_FIELD" not in testo:
        testo = re.sub(r"^(BASEROW_PRIMANOTA_TABLE_ID\s*=.*)$",
                       r"\1\nBASEROW_UTENTE_MENU_PRIMANOTA_FIELD = None   # casella Menu_PrimaNota della tabella Utenti",
                       testo, count=1, flags=re.M)
    if table_id:
        testo = re.sub(r"^BASEROW_PRIMANOTA_TABLE_ID\s*=.*$", f"BASEROW_PRIMANOTA_TABLE_ID = {int(table_id)}",
                       testo, flags=re.M)
    if campo_menu:
        testo = re.sub(r"^BASEROW_UTENTE_MENU_PRIMANOTA_FIELD\s*=.*$",
                       f'BASEROW_UTENTE_MENU_PRIMANOTA_FIELD = "{campo_menu}"   # casella Menu_PrimaNota della tabella Utenti',
                       testo, flags=re.M)
    return testo


def modifica_urls(testo):
    if "primanota.urls" in testo:
        return testo
    m = re.search(r"urlpatterns\s*=\s*\[(.*?)\n\]", testo, re.S)
    if not m:
        raise ValueError("urlpatterns non trovato in urls.py")
    testo = testo[:m.end() - 1] + '    path("primanota/", include("primanota.urls")),\n' + testo[m.end() - 1:]
    if not re.search(r"from django\.urls import[^\n]*\binclude\b", testo):
        testo = "from django.urls import include\n" + testo
    return testo


def modifica_menu(testo):
    if "primanota_visibile" in testo:
        return testo
    if "{% load static %}" not in testo:
        raise ValueError("{% load static %} non trovato nel menu")
    testo = testo.replace("{% load static %}", "{% load static %}\n{% load primanota_menu %}", 1)
    for ancora in ("        {% if show_segnalazioni %}", "        {% if show_scansioni %}"):
        if ancora in testo:
            return testo.replace(ancora, CARD_MENU + ancora, 1)
    raise ValueError("posizione delle schede non trovata nel menu")


def valore_settings(testo, nome, predefinito=None):
    m = re.search(rf"^{nome}\s*=\s*(.+?)\s*(#.*)?$", testo, re.M)
    if not m:
        return predefinito
    valore = m.group(1).strip().strip("'\"")
    return None if valore == "None" else valore


# ---------------------------------------------------------------- Baserow

class Baserow:
    def __init__(self, api_url):
        api_url = api_url.rstrip("/")
        self.base = api_url[:-4] if api_url.endswith("/api") else api_url
        self.jwt = None

    def chiama(self, metodo, percorso, dati=None):
        richiesta = urllib.request.Request(
            self.base + percorso, method=metodo,
            data=json.dumps(dati).encode() if dati is not None else None,
            headers={"Content-Type": "application/json", **({"Authorization": f"JWT {self.jwt}"} if self.jwt else {})})
        try:
            with urllib.request.urlopen(richiesta, timeout=30) as r:
                corpo = r.read()
                return json.loads(corpo) if corpo else {}
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Baserow {metodo} {percorso}: {exc.code} {exc.read().decode(errors='replace')[:300]}")

    def accedi(self, email, password):
        r = self.chiama("POST", "/api/user/token-auth/", {"email": email, "password": password})
        self.jwt = r.get("access_token") or r.get("token")
        if not self.jwt:
            raise RuntimeError("accesso a Baserow non riuscito")

    def crea_campo_menu(self, utenti_id):
        """Casella "Menu_PrimaNota" nella tabella Utenti (come Menu_Scansioni). Restituisce "field_<id>"."""
        for c in self.chiama("GET", f"/api/database/fields/table/{utenti_id}/"):
            if c["name"] == CAMPO_MENU:
                return f"field_{c['id']}", False
        c = self.chiama("POST", f"/api/database/fields/table/{utenti_id}/", {"name": CAMPO_MENU, "type": "boolean"})
        return f"field_{c['id']}", True

    def crea_tabella(self, utenti_id, negozi_id):
        """Crea la tabella nello stesso database della tabella Utenti; se esiste già la riusa."""
        database_id = self.chiama("GET", f"/api/database/tables/{utenti_id}/")["database_id"]
        for t in self.chiama("GET", f"/api/database/tables/database/{database_id}/"):
            if t["name"] == NOME_TABELLA:
                return t["id"], False
        tabella = self.chiama("POST", f"/api/database/tables/database/{database_id}/",
                              {"name": NOME_TABELLA, "data": [["Data Documento"]], "first_row_header": True})
        tid = tabella["id"]
        campi = self.chiama("GET", f"/api/database/fields/table/{tid}/")
        primario = next(c for c in campi if c.get("primary"))
        self.chiama("PATCH", f"/api/database/fields/{primario['id']}/",
                    {"name": "Data Documento", "type": "date", "date_format": "EU", "date_include_time": False})
        data_ora = {"type": "date", "date_format": "EU", "date_include_time": True, "date_time_format": "24"}
        collega = lambda t: {"type": "link_row", "link_row_table_id": int(t), "has_related_field": False}
        for nome, tipo in [
            ("Negozio", collega(negozi_id)),
            ("Attivo", {"type": "boolean"}),
            ("Tipo Documento", {"type": "text"}),
            ("Cassa", {"type": "number", "number_decimal_places": 0}),
            ("Documento", {"type": "file"}),
            ("Note", {"type": "long_text"}),
            ("Caricato Da", collega(utenti_id)),
            ("Data Upload", data_ora),
            ("Lavorato", {"type": "boolean"}),
            ("Lavorato Da", collega(utenti_id)),
            ("Data Lavorazione", data_ora),
            ("Versamento Lavorato", {"type": "boolean"}),
            ("Versamento Lavorato Da", collega(utenti_id)),
            ("Data Lavorazione Versamento", data_ora),
        ]:
            self.chiama("POST", f"/api/database/fields/table/{tid}/", {"name": nome, **tipo})
        return tid, True


# ---------------------------------------------------------------- ambiente Python del portale

def _ha_django(python):
    return subprocess.run([python, "-c", "import django"], capture_output=True).returncode == 0


def python_del_portale(portale, indicato=None):
    """Il Python con cui gira il portale: quello indicato, quello del processo attivo, un venv o il sistema."""
    candidati = [indicato] if indicato else []
    # Processo del portale in esecuzione (runserver, gunicorn, uwsgi...) con cartella di lavoro nel portale.
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            comando = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if ("manage.py" in comando or "tocal.wsgi" in comando) and str(portale) in os.readlink(proc / "cwd"):
                candidati.append(os.readlink(proc / "exe"))
        except OSError:
            continue
    # Non si risolvono i link: il python di un venv è un link a quello di sistema.
    candidati += [os.path.abspath(portale / c) for c in ("venv/bin/python", ".venv/bin/python", "env/bin/python", "../venv/bin/python")]
    candidati += [shutil.which("python3"), sys.executable]
    for c in candidati:
        if c and os.path.isfile(c) and _ha_django(c):
            return c
    return None


def proprietario(portale):
    """L'utente a cui appartiene il portale: file nuovi e crontab vanno a lui, non a root."""
    return pwd.getpwuid((portale / "manage.py").stat().st_uid).pw_name


def dai_a(utente, *percorsi):
    if os.geteuid() != 0:
        return
    info = pwd.getpwnam(utente)
    for radice in percorsi:
        for p in [radice, *Path(radice).rglob("*")]:
            os.chown(p, info.pw_uid, info.pw_gid)


def esegui(comando, cwd):
    print("  $ " + " ".join(comando))
    r = subprocess.run(comando, cwd=cwd, capture_output=True, text=True)
    uscita = (r.stdout + r.stderr).strip()
    if uscita:
        print("    " + uscita.replace("\n", "\n    ")[-2500:])
    return r.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Installa la Prima Nota nel portale TOCAL")
    parser.add_argument("--portale", default="/opt/tocal")
    parser.add_argument("--senza-baserow", action="store_true")
    parser.add_argument("--senza-cron", action="store_true")
    parser.add_argument("--solo-file", action="store_true")
    parser.add_argument("--python", help="Python del portale, se non viene trovato da solo")
    args = parser.parse_args()

    portale = Path(args.portale).resolve()
    # Nello zip la cartella primanota sta accanto allo script; nel repository un livello sopra.
    sorgente = QUI / "primanota" if (QUI / "primanota").is_dir() else QUI.parent / "primanota"
    settings = portale / "tocal" / "settings.py"
    urls = portale / "tocal" / "urls.py"
    menu = portale / "core" / "templates" / "core" / "menu.html"
    archivio = portale / "primanota_archivio"

    titolo("Controlli")
    for p in (portale / "manage.py", settings, urls, menu, portale / "scansioni", sorgente):
        if not p.exists():
            errore(f"Non trovo {p}. Lanciare lo script dalla cartella estratta dallo zip, con --portale se il portale non è in /opt/tocal.")
    ok(f"portale in {portale}")

    titolo("Copia di sicurezza")
    backup = Backup(portale)
    for p in (settings, urls, menu, portale / "db.sqlite3", portale / "primanota", portale / "tocal" / "primanota"):
        backup.salva(p)
    cron = ["crontab"] + (["-u", proprietario(portale)] if os.geteuid() == 0 else [])
    try:
        crontab_prima = subprocess.run(cron + ["-l"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        crontab_prima = None
    if crontab_prima:
        (backup.cartella / "crontab.txt").write_text(crontab_prima)
    ok(f"salvata in {backup.cartella}")

    try:
        titolo("Cartella primanota")
        sbagliata = portale / "tocal" / "primanota"
        if sbagliata.exists():
            shutil.rmtree(sbagliata)
            ok(f"tolta la copia messa per errore in {sbagliata} (è nel backup)")
        destinazione = portale / "primanota"
        if destinazione.exists():
            shutil.rmtree(destinazione)
        shutil.copytree(sorgente, destinazione, ignore=shutil.ignore_patterns("__pycache__"))
        archivio.mkdir(parents=True, exist_ok=True)
        utente = proprietario(portale)
        dai_a(utente, destinazione, archivio)
        ok(f"copiata in {destinazione}; archivio SysSpy in {archivio} (utente {utente})")

        titolo("settings.py, urls.py e menu")
        testo_settings = modifica_settings(settings.read_text(encoding="utf-8"), archivio=archivio)
        settings.write_text(testo_settings, encoding="utf-8")
        urls.write_text(modifica_urls(urls.read_text(encoding="utf-8")), encoding="utf-8")
        menu.write_text(modifica_menu(menu.read_text(encoding="utf-8")), encoding="utf-8")
        ok("modificati (solo aggiunte)")

        titolo("Baserow: tabella Prima Nota e casella Menu_PrimaNota negli Utenti")
        table_id = valore_settings(testo_settings, "BASEROW_PRIMANOTA_TABLE_ID")
        campo_menu = valore_settings(testo_settings, "BASEROW_UTENTE_MENU_PRIMANOTA_FIELD")
        if table_id and campo_menu:
            ok(f"già configurate: tabella {table_id}, casella {campo_menu}")
        elif args.senza_baserow:
            avviso("saltato: indicare a mano BASEROW_PRIMANOTA_TABLE_ID e BASEROW_UTENTE_MENU_PRIMANOTA_FIELD in settings.py")
        else:
            api = valore_settings(testo_settings, "BASEROW_API_URL")
            utenti_id = valore_settings(testo_settings, "BASEROW_UTENTI_TABLE_ID", "272")
            negozi_id = valore_settings(testo_settings, "BASEROW_NEGOZI_TABLE_ID", "880")
            print(f"  Serve un utente Baserow con permessi di amministrazione ({api}).")
            email = input("  Email Baserow (Invio per saltare): ").strip()
            if not email:
                avviso("saltato: indicare a mano BASEROW_PRIMANOTA_TABLE_ID e BASEROW_UTENTE_MENU_PRIMANOTA_FIELD in settings.py")
            else:
                b = Baserow(api)
                b.accedi(email, getpass.getpass("  Password Baserow: "))
                if not table_id:
                    table_id, creata = b.crea_tabella(utenti_id, negozi_id)
                    ok(f"tabella «{NOME_TABELLA}» {'creata' if creata else 'già esistente'}: id {table_id}")
                if not campo_menu:
                    campo_menu, creato = b.crea_campo_menu(utenti_id)
                    ok(f"casella «{CAMPO_MENU}» nella tabella Utenti {'creata' if creato else 'già esistente'}: {campo_menu}")
                settings.write_text(modifica_settings(settings.read_text(encoding="utf-8"), table_id=table_id,
                                                      campo_menu=campo_menu), encoding="utf-8")
                ok("scritti in settings.py")

        if args.solo_file:
            titolo("Fatto (solo file)")
            return

        titolo("Dipendenze e database")
        python = python_del_portale(portale, args.python)
        if not python:
            raise RuntimeError("non trovo il Python con Django del portale: rilanciare con --python /percorso/python")
        print(f"  Python del portale: {python}")
        if not esegui([python, "-m", "pip", "install", "-q", "smbprotocol", "cryptography", "pymupdf"], portale):
            avviso("pip non è riuscito: installare a mano smbprotocol, cryptography e pymupdf")
        if not esegui([python, "manage.py", "migrate", "primanota"], portale):
            raise RuntimeError("migrate non riuscito")
        if not esegui([python, "manage.py", "check"], portale):
            raise RuntimeError("il controllo del portale ha trovato errori")

        dai_a(utente, archivio)
    except Exception as exc:
        print(f"\n  ✗ {exc}\n  Rimetto a posto i file dalla copia di sicurezza…")
        backup.ripristina()
        # Ciò che non esisteva prima si toglie (l'archivio solo se ancora vuoto).
        if (portale / "primanota").exists() and portale / "primanota" not in backup.salvati:
            shutil.rmtree(portale / "primanota")
        if archivio.is_dir() and not any(archivio.iterdir()):
            archivio.rmdir()
        errore("Installazione annullata. Il portale è come prima.")

    titolo("Rielaborazione dei SysSpy già archiviati (in background)")
    # Divide per giornata i file già importati e ricalcola pagamenti e controlli. Con uno storico
    # grande richiede tempo: gira in background con l'utente del portale e riprende da dove era
    # arrivata se viene interrotta. L'installazione intanto prosegue.
    log_rielabora = (portale / "logs" if (portale / "logs").is_dir() else archivio) / "primanota_rielaborazione.log"
    comando = [python, "manage.py", "importa_sysspy", "--rielabora"]
    if os.geteuid() == 0 and utente != "root":
        comando = ["sudo", "-u", utente] + comando
    with open(log_rielabora, "a") as uscita:
        subprocess.Popen(comando, cwd=portale, stdout=uscita, stderr=subprocess.STDOUT, start_new_session=True)
    dai_a(utente, log_rielabora)
    ok(f"avviata: per seguirla  tail -f {log_rielabora}")

    if not args.senza_cron and crontab_prima is not None:
        titolo("Importazione automatica")
        # Il crontab lancia il comando ogni 5 minuti; gli orari veri si decidono nel portale
        # (Prima Nota > Condivisioni negozi). Le righe di una installazione precedente si sostituiscono.
        log = (portale / "logs" if (portale / "logs").is_dir() else archivio) / "primanota_importazione.log"
        riga = f"*/5 * * * * cd {portale} && {python} manage.py importa_sysspy --pianificato >> {log} 2>&1"
        vecchie = crontab_prima.splitlines()
        tenute = [r for r in vecchie if r != MARCATORE_CRON and "importa_sysspy" not in r]
        nuovo = "\n".join(tenute + [MARCATORE_CRON, riga]) + "\n"
        if nuovo.strip() == crontab_prima.strip():
            ok("già presente nel crontab")
        else:
            subprocess.run(cron + ["-"], input=nuovo, text=True, check=True)
            ok("crontab aggiornato: gli orari si decidono in Prima Nota > Condivisioni negozi")

    titolo("Riavvio del portale")
    riavviato = False
    servizio = "tocal.service"
    if shutil.which("systemctl") and os.geteuid() == 0 and \
            subprocess.run(["systemctl", "cat", servizio], capture_output=True).returncode == 0:
        esegui(["systemctl", "restart", servizio], portale)
        riavviato = subprocess.run(["systemctl", "is-active", "--quiet", servizio]).returncode == 0
        if riavviato:
            ok(f"{servizio} riavviato e attivo")
        else:
            avviso(f"{servizio} non risulta attivo: controllare con  journalctl -u {servizio} -n 50")
    else:
        avviso("servizio tocal.service non trovato: riavviare il portale come di consueto")

    titolo("Fatto")
    print(f"""  Ora:
  1. {"portale già riavviato" if riavviato else "riavviare il portale come di consueto"};
  2. Menu > Prima Nota > Condivisioni negozi: indicare la cartella SysSpy di ogni negozio e premere «Importa nuovi».
  Per tornare indietro: i file originali sono in {backup.cartella}""")


if __name__ == "__main__":
    main()
