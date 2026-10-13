// La pagina del banco: avanti, indietro, ripeti, imposta, azzera.
// JavaScript volutamente semplice (niente moduli né sintassi recente): deve
// funzionare anche nei browser integrati delle bilance.
(function () {
  "use strict";

  var OGNI = 2000;
  function parametro(nome, testo) {
    var trovato = new RegExp("[?#&]" + nome + "=([^&]*)").exec(testo);
    return trovato ? decodeURIComponent(trovato[1]) : null;
  }
  // Gli utenti di piattaforma scelgono il cliente: dall'indirizzo, o dalla scelta ricordata.
  var cliente = parametro("cliente", location.search) || memoria("futurapro.banco.cliente");
  var modoChiave = parametro("modo", location.search) === "chiave";
  var contenitore = document.getElementById("reparti");
  var statoEl = document.getElementById("stato");
  var schede = {};

  function memoria(chiave, valore) {
    try {
      if (valore === undefined) return localStorage.getItem(chiave);
      if (valore === null) localStorage.removeItem(chiave);
      else localStorage.setItem(chiave, valore);
    } catch (e) {
      return null;
    }
  }

  function cookie(nome) {
    var trovato = document.cookie.split("; ").filter(function (c) { return c.indexOf(nome + "=") === 0; })[0];
    return trovato ? decodeURIComponent(trovato.split("=")[1]) : "";
  }

  function richiesta(metodo, url, dati, intestazioni, fatto) {
    var xhr = new XMLHttpRequest();
    xhr.open(metodo, url, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    for (var nome in intestazioni) xhr.setRequestHeader(nome, intestazioni[nome]);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var corpo = null;
      try { corpo = JSON.parse(xhr.responseText); } catch (e) { corpo = null; }
      fatto(xhr.status, corpo);
    };
    xhr.send(dati ? JSON.stringify(dati) : null);
  }

  function segnala(ok, testo) {
    statoEl.textContent = testo;
    statoEl.className = "stato " + (ok ? "ok" : "ko");
  }

  // --- Le due modalità: sessione del pannello o chiave del reparto ------------

  // Il pannello dà un link /banco/#chiave=…: la chiave si salva sul dispositivo e sparisce
  // dall'indirizzo (la parte dopo # non arriva mai al server, quindi nemmeno nei suoi log).
  var dalLink = parametro("chiave", location.hash);
  if (dalLink) {
    memoria("futurapro.banco.chiave", dalLink);
    if (history.replaceState) history.replaceState(null, "", location.pathname + location.search);
  }
  var chiave = memoria("futurapro.banco.chiave") || dalLink;
  var modo = chiave ? "chiave" : "sessione";

  // In HTTP passano solo le chiamate con la chiave (bilance): con l'accesso del
  // pannello serve HTTPS, quindi senza chiave si passa subito alla versione sicura.
  if (location.protocol === "http:" && modo === "sessione" && !modoChiave) {
    location.replace("https://" + location.host + location.pathname + location.search);
    return;
  }

  function intestazioni() {
    if (modo === "chiave") return { Authorization: "Pulsante " + chiave };
    var h = { "X-CSRFToken": cookie("csrftoken") };
    if (cliente) h["X-Cliente"] = cliente;
    return h;
  }

  function urlOperazione(reparto, operazione) {
    return modo === "chiave" ? "/api/eliminacode/pulsante/" + operazione + "/" : "/api/reparti/" + reparto.id + "/" + operazione + "/";
  }

  function carica() {
    var url = modo === "chiave" ? "/api/eliminacode/pulsante/" : "/api/reparti/";
    richiesta("GET", url, null, intestazioni(), function (codice, corpo) {
      if (codice === 401 && modo === "chiave") {
        memoria("futurapro.banco.chiave", null);
        location.reload();
        return;
      }
      if (codice === 403 || codice === 401) {
        document.getElementById("accesso").hidden = false;
        segnala(false, "Non collegato");
        return;
      }
      if (codice === 400 && modo === "sessione") {
        // Utente di piattaforma senza cliente scelto: si chiede quale.
        scegliCliente();
        return;
      }
      if (codice === 404 && cliente) {
        memoria("futurapro.banco.cliente", null);
        cliente = null;
        scegliCliente();
        return;
      }
      if (codice === 0) {
        segnala(false, "Server non raggiungibile");
        return;
      }
      if (codice !== 200) {
        segnala(false, "Errore " + codice);
        return;
      }
      segnala(true, "Collegato");
      var reparti = modo === "chiave" ? [corpo] : corpo.results.filter(function (r) { return r.attivo; });
      reparti.forEach(mostra);
    });
  }

  var sceltaMostrata = false;
  function scegliCliente() {
    segnala(false, "Scegli il cliente");
    if (sceltaMostrata) return;
    sceltaMostrata = true;
    richiesta("GET", "/api/piattaforma/clienti/", null, intestazioni(), function (codice, corpo) {
      if (codice !== 200 || !corpo) return;
      var box = document.createElement("section");
      box.className = "scheda";
      var titolo = document.createElement("h2");
      titolo.textContent = "Di quale cliente?";
      var scelta = document.createElement("select");
      var vuota = document.createElement("option");
      vuota.textContent = "— scegli —";
      vuota.value = "";
      scelta.appendChild(vuota);
      corpo.results.forEach(function (c) {
        var o = document.createElement("option");
        o.value = c.id;
        o.textContent = c.nome;
        scelta.appendChild(o);
      });
      scelta.onchange = function () {
        if (!scelta.value) return;
        memoria("futurapro.banco.cliente", scelta.value);
        location.reload();
      };
      box.appendChild(titolo);
      box.appendChild(scelta);
      contenitore.appendChild(box);
    });
  }

  // --- Una scheda per reparto ---------------------------------------------------

  function pulsante(testo, classe, azione) {
    var b = document.createElement("button");
    b.textContent = testo;
    b.className = classe;
    b.onclick = azione;
    return b;
  }

  function esegui(reparto, operazione, dati) {
    richiesta("POST", urlOperazione(reparto, operazione), dati, intestazioni(), function (codice, corpo) {
      if (codice === 200 && corpo) mostra(corpo);
      else segnala(false, "Operazione non riuscita (" + codice + ")");
    });
  }

  function mostra(reparto) {
    var scheda = schede[reparto.id];
    if (!scheda) {
      var el = document.createElement("section");
      el.className = "scheda";
      el.style.borderTopColor = reparto.colore;
      var nome = document.createElement("h2");
      nome.textContent = reparto.nome;
      var numero = document.createElement("div");
      numero.className = "numero";
      numero.style.color = reparto.colore;
      var coda = document.createElement("div");
      coda.className = "coda";
      var comandi = document.createElement("div");
      comandi.className = "comandi";
      comandi.appendChild(pulsante("AVANTI", "primario avanti", function () { esegui(reparto, "avanti"); }));
      comandi.appendChild(pulsante("Indietro", "", function () { esegui(reparto, "indietro"); }));
      comandi.appendChild(pulsante("Ripeti", "", function () { esegui(reparto, "ripeti"); }));
      {
        comandi.appendChild(pulsante("Imposta…", "", function () {
          var n = prompt("Da quale numero ripartire? (da 0 a " + (reparto.massimo || 99) + ")");
          if (n !== null && /^\d+$/.test(n)) esegui(reparto, "imposta", { numero: parseInt(n, 10) });
        }));
        comandi.appendChild(pulsante("Azzera", "pericolo", function () {
          if (confirm("Azzerare la coda di " + reparto.nome + "?")) esegui(reparto, "azzera");
        }));
      }
      el.appendChild(nome);
      el.appendChild(numero);
      el.appendChild(coda);
      el.appendChild(comandi);
      contenitore.appendChild(el);
      scheda = schede[reparto.id] = { numero: numero, coda: coda };
    }
    scheda.numero.textContent = reparto.numero === null || reparto.numero === undefined ? "–" : reparto.numero;
    scheda.coda.textContent = "Clienti in coda: " + reparto.in_coda;
  }

  // --- Avvio -----------------------------------------------------------------------

  if (modoChiave && !chiave) {
    document.getElementById("chiave").hidden = false;
    document.getElementById("chiave-salva").onclick = function () {
      var testo = document.getElementById("chiave-testo").value.trim();
      if (testo) {
        memoria("futurapro.banco.chiave", testo);
        location.href = location.pathname;
      }
    };
    segnala(false, "Da collegare");
    return;
  }
  carica();
  setInterval(carica, OGNI);
})();
