// Le regole del palinsesto, identiche a server/contenuti/palinsesto.py:
// se cambiano lì, cambiano qui.

// Data, giorno della settimana (0 = lunedì) e ora nel fuso del manifest,
// qualunque sia il fuso impostato sul dispositivo.
export function istanteNelFuso(fuso, quando = new Date()) {
  const parti = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: fuso, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", weekday: "short", hourCycle: "h23",
    }).formatToParts(quando).map((p) => [p.type, p.value]),
  );
  const giorni = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
  return {
    data: `${parti.year}-${parti.month}-${parti.day}`,
    giorno: giorni[parti.weekday],
    ora: `${parti.hour}:${parti.minute}:${parti.second}`,
  };
}

// Date "AAAA-MM-GG" e orari "HH:MM:SS" si confrontano come stringhe.
function nellOrario(ora, inizio, fine) {
  if (!inizio && !fine) return true;
  inizio = inizio || "00:00:00";
  if (!fine) return ora >= inizio;
  if (inizio <= fine) return inizio <= ora && ora < fine;
  return ora >= inizio || ora < fine; // scavalca la mezzanotte
}

export function valida(p, istante) {
  return (
    p.attiva &&
    (!p.data_inizio || istante.data >= p.data_inizio) &&
    (!p.data_fine || istante.data <= p.data_fine) &&
    (!p.giorni.length || p.giorni.includes(istante.giorno)) &&
    nellOrario(istante.ora, p.ora_inizio, p.ora_fine)
  );
}

// Le pubblicazioni arrivano già in ordine di creazione a pari priorità.
export function inOnda(pubblicazioni, istante) {
  const valide = pubblicazioni.filter((p) => valida(p, istante));
  if (!valide.length) return [];
  const massima = Math.max(...valide.map((p) => p.priorita));
  return valide.filter((p) => p.priorita === massima);
}

// Lo schermo è acceso in questo istante? «accensione» viene dal manifest: null = sempre.
// Una fascia che passa la mezzanotte (22:00–02:00 del venerdì) vale fino alle 2 di sabato.
export function acceso(accensione, istante) {
  if (!accensione) return true;
  if ((accensione.chiusure || []).includes(istante.data)) return false;
  const ora = istante.ora.slice(0, 5);
  const ieri = (istante.giorno + 6) % 7;
  return (accensione.fasce || []).some((f) => {
    if (f.dalle < f.alle) return f.giorni.includes(istante.giorno) && f.dalle <= ora && ora < f.alle;
    return (f.giorni.includes(istante.giorno) && ora >= f.dalle) || (f.giorni.includes(ieri) && ora < f.alle);
  });
}
