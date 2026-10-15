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
