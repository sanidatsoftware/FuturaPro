// Gli stessi casi di contenuti/tests.py (RegoleTest): il player deve decidere come il server.
// Esecuzione: node --test server/player/static/player/
import assert from "node:assert/strict";
import { test } from "node:test";

import { inOnda, istanteNelFuso, valida } from "./regole.js";

const regola = (campi) => ({
  attiva: true, data_inizio: null, data_fine: null, ora_inizio: null, ora_fine: null,
  giorni: [], priorita: 0, ...campi,
});
const lunedi9 = { data: "2026-10-12", giorno: 0, ora: "09:00:00" };

test("fascia oraria, fine esclusa", () => {
  assert.ok(valida(regola({ ora_inizio: "08:00:00", ora_fine: "12:00:00" }), lunedi9));
  assert.ok(!valida(regola({ ora_inizio: "09:01:00", ora_fine: "12:00:00" }), lunedi9));
  assert.ok(!valida(regola({ ora_inizio: "08:00:00", ora_fine: "09:00:00" }), lunedi9));
});

test("fascia che scavalca la mezzanotte", () => {
  const notte = regola({ ora_inizio: "22:00:00", ora_fine: "06:00:00" });
  assert.ok(valida(notte, { ...lunedi9, ora: "23:30:00" }));
  assert.ok(valida(notte, { data: "2026-10-13", giorno: 1, ora: "05:59:00" }));
  assert.ok(!valida(notte, lunedi9));
});

test("giorni e date", () => {
  assert.ok(valida(regola({ giorni: [0, 2] }), lunedi9));
  assert.ok(!valida(regola({ giorni: [5, 6] }), lunedi9));
  assert.ok(valida(regola({ data_inizio: "2026-10-12", data_fine: "2026-10-12" }), lunedi9));
  assert.ok(!valida(regola({ data_fine: "2026-10-11" }), lunedi9));
  assert.ok(!valida(regola({ attiva: false }), lunedi9));
});

test("vince la priorità, poi si accoda", () => {
  const prima = regola({ nome: "prima" });
  const seconda = regola({ nome: "seconda" });
  const urgente = regola({ nome: "urgente", priorita: 10, ora_inizio: "08:00:00", ora_fine: "10:00:00" });
  assert.deepEqual(inOnda([prima, seconda], lunedi9).map((p) => p.nome), ["prima", "seconda"]);
  assert.deepEqual(inOnda([urgente, prima], lunedi9).map((p) => p.nome), ["urgente"]);
  assert.deepEqual(inOnda([urgente, prima], { ...lunedi9, ora: "11:00:00" }).map((p) => p.nome), ["prima"]);
});

test("l'istante è nel fuso del manifest, non in quello del dispositivo", () => {
  // 22:30 UTC di domenica 11 ottobre 2026 = 00:30 di lunedì 12 a Roma (ora legale).
  assert.deepEqual(istanteNelFuso("Europe/Rome", new Date("2026-10-11T22:30:00Z")), {
    data: "2026-10-12", giorno: 0, ora: "00:30:00",
  });
});

test("accensione: fasce, chiusure e mezzanotte", async () => {
  const { acceso } = await import("./regole.js");
  const orario = { fasce: [{ giorni: [0, 1, 2, 3, 4, 5], dalle: "07:30", alle: "21:00" }, { giorni: [4], dalle: "22:00", alle: "02:00" }], chiusure: ["2026-12-25"] };
  assert.ok(acceso(null, lunedi9));
  assert.ok(acceso(orario, lunedi9));
  assert.ok(!acceso(orario, { ...lunedi9, ora: "21:00:00" }));
  assert.ok(!acceso(orario, { data: "2026-10-18", giorno: 6, ora: "10:00:00" })); // domenica
  assert.ok(acceso(orario, { data: "2026-10-16", giorno: 4, ora: "23:00:00" })); // venerdì sera
  assert.ok(acceso(orario, { data: "2026-10-17", giorno: 5, ora: "01:30:00" })); // e dopo mezzanotte
  assert.ok(!acceso(orario, { data: "2026-12-25", giorno: 4, ora: "10:00:00" })); // chiuso
});
