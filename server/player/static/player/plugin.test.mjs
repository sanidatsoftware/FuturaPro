// node --test plugin.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { codiceBilancia, leggiPrezzo } from "./plugin.js";

test("offerta valida, scaduta o non conveniente", () => {
  const oggi = new Date(2026, 9, 15);
  assert.deepEqual(leggiPrezzo({ prezzo: "1,29", prezzo_offerta: 0.99, offerta_al: "2026-10-31" }, oggi),
    { pieno: 1.29, offerta: 0.99, fino: new Date(2026, 9, 31), unita: "" });
  assert.equal(leggiPrezzo({ prezzo: 1.29, prezzo_offerta: 0.99, offerta_al: "14/10/2026" }, oggi).offerta, null);
  assert.equal(leggiPrezzo({ prezzo: 1.29, prezzo_offerta: 0.99, offerta_dal: "20261020" }, oggi).offerta, null);
  assert.equal(leggiPrezzo({ prezzo: 1.29, prezzo_offerta: 1.5 }, oggi).offerta, null);
  assert.equal(leggiPrezzo({ prezzo: 1.29, prezzo_offerta: 0 }, oggi).offerta, null);
  assert.equal(leggiPrezzo({ prezzo: 32.9, unita: "kg" }, oggi).unita, "kg");
});

test("codici bilancia: prefisso, PLU e reparto", () => {
  const config = { prefissi: [{ prefisso: "20", reparto: "Salumeria", codice: "1" }, { prefisso: "21", reparto: "Panetteria", codice: "" }], plu_inizio: 3, plu_lunghezza: 5 };
  assert.deepEqual(codiceBilancia("2000123012345", config), { plu: "00123", reparto: "1", nomeReparto: "Salumeria" });
  assert.equal(codiceBilancia("2100123012345", config).reparto, "21");
  assert.equal(codiceBilancia("8001234567890", config), null);
  assert.equal(codiceBilancia("20001230", config), null);
  assert.equal(codiceBilancia("2000123012345", null), null);
});

test("testi della bilancia: righe ricomposte, prefisso tolto, allergeni separati", async () => {
  const { testoEtichetta, separaAllergeni } = await import("./plugin.js");
  const testo = "INGREDIENTI: carne di suino - sale - pepe nero - a\r\ncqua - aceto aromatico. FATTORI ALLERGENI: GLU\r\nTINE, LATTE E DERIVATI.";
  const pulito = testoEtichetta(testo);
  assert.equal(pulito, "carne di suino - sale - pepe nero - acqua - aceto aromatico. FATTORI ALLERGENI: GLUTINE, LATTE E DERIVATI.");
  assert.deepEqual(separaAllergeni(pulito), ["carne di suino - sale - pepe nero - acqua - aceto aromatico", "GLUTINE, LATTE E DERIVATI."]);
  // Riga corta: a capo fra due parole.
  assert.equal(testoEtichetta("grana - granella di pistacchio - farina\r\ndi pistacchio - pesto di pistacchio - pangrattato x"), "grana - granella di pistacchio - farina di pistacchio - pesto di pistacchio - pangrattato x");
  assert.equal(testoEtichetta("Ingr.: latte - sale"), "latte - sale");
  assert.equal(testoEtichetta(null), "");
});

test("testi della bilancia: cambio di scrittura e sigle", async () => {
  const { testoEtichetta } = await import("./plugin.js");
  assert.equal(testoEtichetta("Latte non pastorizzato, sale, caglio microbico\r\nNATURALMENTE SENZA LATTOSIO"), "Latte non pastorizzato, sale, caglio microbico NATURALMENTE SENZA LATTOSIO");
  assert.equal(testoEtichetta("carne - Mix dry 17041- ROSSO PIU con una riga lunga\r\nA.G."), "carne - Mix dry 17041- ROSSO PIU con una riga lunga A.G.");
});
