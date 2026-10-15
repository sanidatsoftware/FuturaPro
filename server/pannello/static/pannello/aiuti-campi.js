// Le spiegazioni dei campi, scheda per scheda: si applicano da sole a ogni etichetta di campo
// («label.campo») e di spunta («label.spunta») che compare nella scheda, anche dopo (es. le
// proprietà dell'elemento scelto nell'editor del ticket). La chiave è l'inizio dell'etichetta.

const PLUGIN = {
  "Info Prezzo attivo": "Acceso: i dispositivi del negozio rispondono al lettore di codici a barre. Spento: il lettore viene ignorato.",
  "Info Ingredienti attivo": "Acceso: le etichette della bilancia (con i prefissi indicati sotto) mostrano gli ingredienti. Spento: vengono ignorate.",
  "Il riquadro resta per": "Per quanti secondi resta a schermo la risposta. Una nuova lettura la sostituisce subito; un tocco sul riquadro lo chiude.",
  "Mostra anche il prezzo": "Insieme agli ingredienti mostra il prezzo, preso da Info Prezzo (deve essere attivo). Se Info Prezzo non lo trova, si usa quello della bilancia.",
  "Gestionale": "Per i gestionali conosciuti (EvoPos, DIGI) la ricerca è già pronta. «Altro»: indichi tu tabella e colonne del file, o scrivi la query.",
  "Tabella": "Il nome della tabella del file .db che contiene i prodotti (si vede aprendo il file con «DB Browser for SQLite» o con struttura-sqlite.ps1).",
  "Colonna del codice": "La colonna con il codice a barre (EAN) che il lettore legge.",
  "Colonna della descrizione": "La colonna con il nome del prodotto da mostrare.",
  "Colonna del prezzo in offerta": "Facoltativa: il prezzo scontato. Se è più basso del prezzo normale compare il banner «Offerta».",
  "Colonna del prezzo": "La colonna con il prezzo di vendita (IVA compresa).",
  "Colonna inizio offerta": "Facoltativa: da quando vale l'offerta. Prima di quella data l'offerta non si mostra.",
  "Colonna fine offerta": "Facoltativa: fino a quando vale l'offerta; compare anche nel riquadro («valida fino al…»).",
  "Colonna unità": "Facoltativa: l'unità del prezzo (es. kg): si mostra «€ / kg».",
  "Colonna PLU": "Il numero del prodotto nella bilancia (PLU): serve per le etichette con il peso.",
  "Colonna reparto": "Facoltativa: il banco del prodotto. Serve quando lo stesso PLU esiste in banchi diversi.",
  "Colonna degli ingredienti": "La colonna con l'elenco degli ingredienti.",
  "Colonna degli allergeni": "Facoltativa: gli allergeni, mostrati a parte e in evidenza. Senza, si cercano nel testo («ALLERGENI: …») e si evidenziano le parole in MAIUSCOLO.",
  "Colonna modalità di conservazione": "Facoltativa: come conservare il prodotto (es. «tra 0 e 4 °C»).",
  "Il PLU inizia dalla cifra": "In quale cifra dell'etichetta inizia il numero del prodotto. Es. «20 00123 01234 5»: dalla 3ª.",
  "Lunghezza del PLU": "Quante cifre è lungo il numero del prodotto nell'etichetta (di solito 5).",
  "Carattere": "Il tipo di carattere del riquadro sullo schermo.",
  "Grandezza testo": "Più grande o più piccolo rispetto alla grandezza automatica (100% = normale).",
  "Larghezza": "Quanta parte della larghezza dello schermo occupa il riquadro.",
  "Posizione": "Dove compare il riquadro: al centro, in alto o in basso.",
  "Sfondo banner": "Il colore della fascia «Offerta».",
  "Sfondo": "Il colore di fondo del riquadro.",
  "Testo del banner": "La scritta della fascia in alto per i prodotti in offerta (es. OFFERTA, PROMO, SOTTOCOSTO).",
  "Testo banner": "Il colore della scritta della fascia «Offerta».",
  "Testo": "Il colore del testo del riquadro.",
  "Prezzo in offerta lampeggiante": "Il prezzo scontato lampeggia per attirare l'attenzione.",
  "Prezzo in offerta": "Il colore del prezzo scontato.",
  "Prezzo": "Il colore del prezzo normale.",
  "Allergeni": "Il colore con cui si evidenziano gli allergeni.",
  "Mostra il prezzo pieno barrato": "Nei prodotti in offerta mostra anche il prezzo normale, barrato.",
  "alle": "Copia il file a questi orari (es. 06:30, 13:00): adatto ai file grandi che cambiano di continuo, come quello della bilancia.",
  "ogni": "Controlla il file ogni tot minuti e lo copia solo se è cambiato. Si può usare insieme agli orari.",
  "pulsante:Salva Info": "Salva le impostazioni del plugin: i dispositivi le ricevono entro un minuto.",
  "pulsante:Salva": "Salva il file di questo negozio: il Totem Master lo riceve entro un minuto.",
  "pulsante:Togli": "Toglie il file di questo negozio: lì il plugin non risponderà più.",
  "pulsante:Aggiungi": "Aggiunge il file di questo negozio.",
  "pulsante:✕": "Toglie questo prefisso.",
  "pulsante:+ Prefisso": "Aggiunge un prefisso di etichetta della bilancia.",
};

const STAMPANTI = {
  "Nome": "Un nome per riconoscere la stampante (es. «Epson banco salumi»).",
  "Sede": "Il negozio dove si trova: si potrà abbinare solo ai totem di quel negozio.",
  "Tipo": "Epson di rete: il totem stampa direttamente all'indirizzo IP (ePOS-Print). Stampante di sistema: quella predefinita di Windows sul PC del totem (es. USB con driver Epson).",
  "Indirizzo IP": "L'indirizzo fisso della stampante in rete (si legge sullo scontrino di prova della stampante).",
  "Modello": "Il modello decide la larghezza stampabile del biglietto (es. TM-T20IV: 72 mm su carta da 80).",
  "Carta": "La larghezza del rotolo montato: 80 o 58 mm.",
  "Layout ticket": "Com'è fatto il biglietto (Impostazioni · Layout Ticket). Vuoto: il biglietto semplice.",
  "Intestazione": "Facoltativa: sostituisce l'intestazione del layout solo per questa stampante (es. il nome del negozio).",
  "Messaggio in fondo": "Facoltativo: sostituisce il testo di fine biglietto del layout solo per questa stampante.",
  "Note": "Appunti per chi gestisce (es. dove si trova, numero di serie).",
  "pulsante:Aggiungi stampante": "Aggiunge la stampante all'anagrafica: poi la abbini al totem in «Anagrafica Dispositivi Video».",
  "pulsante:Modifica": "Apre i campi per cambiare questa stampante.",
  "pulsante:Elimina": "Elimina la stampante. I totem abbinati tornano alla stampa indicata nel layout.",
};

const TICKET = {
  "file": "Il logo da stampare in cima al biglietto (PNG o JPG): diventa in bianco e nero alla larghezza della carta.",
  "scelta": "L'elemento da aggiungere: un testo libero, una linea, o un elemento tolto in precedenza.",
  "Nuovo layout": "Il nome del nuovo layout (es. «Biglietto standard», «Biglietto con promo»).",
  "Carta di riferimento": "La carta per cui lo componi. Il totem lo stampa comunque alla larghezza della sua stampante.",
  "Carta": "La larghezza della carta per cui comporre il biglietto.",
  "Anteprima su": "Mostra l'anteprima alla larghezza di una stampante vera.",
  "Nome": "Il nome del layout, da scegliere nell'anagrafica delle stampanti.",
  "Testo": "Il testo da stampare. Per intestazione e fine biglietto, una stampante può averne uno suo.",
  "Larghezza": "Quanta parte della carta occupa (logo e QR).",
  "Spessore": "Lo spessore della linea di separazione.",
  "Carattere": "Il tipo di carattere. Il biglietto si stampa come immagine: va bene qualsiasi carattere installato sul totem.",
  "Grandezza": "In punti della stampante: 8 punti = 1 mm. Il numero del biglietto di solito è tra 150 e 220.",
  "Allineamento": "A sinistra, al centro o a destra della carta.",
  "Formato": "Come si stampa la data del biglietto: data e ora, solo la data, solo l'ora, o per esteso con il giorno della settimana.",
  "Grassetto": "Testo più spesso.",
  "Corsivo": "Testo inclinato.",
  "Tutto maiuscolo": "Scrive il testo in MAIUSCOLO, qualunque cosa arrivi (es. il nome del reparto).",
  "Bianco su nero": "Fascia nera con il testo bianco: fa risaltare l'elemento (es. il reparto).",
  "Spazio sotto": "Lo spazio vuoto dopo l'elemento, in punti (8 = 1 mm).",
  "pulsante:🧾": "Apre questo layout nell'editor.",
  "pulsante:Crea": "Crea il layout con gli elementi di partenza: poi lo componi qui sotto.",
  "pulsante:+ Aggiungi": "Aggiunge l'elemento scelto in fondo al biglietto (poi lo trascini dove vuoi).",
  "pulsante:Togli il logo": "Toglie il logo dal layout.",
  "pulsante:Salva layout": "Salva il layout: le stampanti che lo usano lo ricevono entro un minuto.",
  "pulsante:Ripristina gli elementi di partenza": "Rimette gli elementi e le grandezze di partenza (non salva finché non premi «Salva layout»).",
  "pulsante:Elimina layout": "Elimina il layout. Le stampanti che lo usano tornano al biglietto semplice.",
  "pulsante:Elimina elemento": "Toglie questo elemento dal biglietto.",
  "pulsante:👁": "Nasconde l'elemento (resta nel layout, non si stampa).",
  "pulsante:🚫": "Mostra di nuovo l'elemento.",
};

const SCHERMI = {
  "scelta": "Scegli il valore per questo schermo: si salva subito.",
  "Totem Master": "Il totem che detiene i turni delle code della sede e legge i file dei plugin: uno solo per sede. Gli altri totem e i monitor chiedono a lui numeri, prezzi e ingredienti.",
};


// Validi in tutte le schede (pulsanti e campi ricorrenti), se la scheda non dice altro.
const GENERALI = {
  "pulsante:Salva": "Salva le modifiche di questo riquadro (o di questa riga). Gli schermi le ricevono entro un minuto.",
  "pulsante:Elimina": "Elimina questa voce. Chiede conferma prima di farlo.",
  "pulsante:Rimuovi": "Toglie questa voce. Chiede conferma prima di farlo.",
  "pulsante:Togli": "Toglie questa voce. Chiede conferma prima di farlo.",
  "pulsante:Modifica": "Apre i campi per cambiare questa voce.",
  "pulsante:Annulla": "Chiude senza salvare.",
  "pulsante:Crea": "Crea una nuova voce con i dati indicati qui accanto.",
  "pulsante:Aggiungi": "Aggiunge una nuova voce con i dati indicati qui accanto.",
  "pulsante:Vai alle impostazioni email": "Apre «Impostazioni · Email»: il server di posta da cui partono le email dell'azienda.",
  "pulsante:Imposta il server email": "Apre «Impostazioni · Email»: senza server di posta le email non partono.",
  "pulsante:Invia un'email di prova": "Manda subito un'email di prova, per controllare che la posta funzioni.",
  "pulsante:Crea l'invio": "Crea l'invio automatico del rapporto ai destinatari indicati, con la frequenza scelta.",
  "pulsante:🖨 Stampa o salva in PDF": "Stampa il rapporto come lo vedi, o salvalo in PDF scegliendo «Salva come PDF» come stampante.",
  "pulsante:‹ Più recenti": "Le operazioni più recenti (pagina precedente).",
  "pulsante:Più vecchie ›": "Le operazioni più vecchie (pagina successiva).",
  "Nome": "Un nome per riconoscere la voce nel pannello.",
  "Destinatari": "Gli indirizzi email che ricevono l'invio, separati da virgola.",
  "Quando": "Ogni quanto parte l'invio automatico (es. ogni lunedì per la settimana precedente).",
  "Dal": "Il primo giorno del periodo da mostrare.",
  "Al": "L'ultimo giorno del periodo da mostrare.",
  "Sede": "Il punto vendita.",
  "Colore": "Il colore con cui si presenta.",
  "Email (separate da virgola)": "Chi riceve gli avvisi: uno o più indirizzi email, separati da virgola.",
};

const SCHERMI_TUTTI = {
  "Codice": "Il codice di 6 cifre che lo schermo nuovo mostra all'accensione: abbina lo schermo a questa azienda.",
  "Nome": "Un nome per riconoscere lo schermo (es. «Ingresso», «Totem salumeria»).",
  "Sede": "Il negozio in cui si trova lo schermo.",
  "Tipo": "Monitor orizzontale o totem verticale: decide quali layout e contenuti gli vanno bene.",
  "Tutti": "Gruppo di schermi: riceve le pubblicazioni fatte sul gruppo.",
  "Per tutti i totem": "La riserva da usare su tutti i totem verticali, quando non c'è nulla in onda.",
  "Per tutti i monitor": "La riserva da usare su tutti i monitor orizzontali, quando non c'è nulla in onda.",
  "pulsante:Abbina": "Collega lo schermo che mostra il codice: da quel momento riceve layout e contenuti.",
  "pulsante:Applica a tutti": "Imposta le riserve scelte qui sopra su tutti i totem e su tutti i monitor.",
  "pulsante:Rimuovi": "Scollega lo schermo: tornerà a mostrare il codice di abbinamento.",
  "*spunta": "Il gruppo di schermi: chi è nel gruppo riceve anche le pubblicazioni fatte sul gruppo.",
  "colonna:Gruppi": "I gruppi di cui fa parte lo schermo: riceve anche le pubblicazioni fatte sul gruppo.",
  "colonna:Orientamento": "Come è montato lo schermo: orizzontale (monitor) o verticale (totem).",
  "colonna:Rotazione": "Ruota l'immagine se lo schermo è montato girato (es. 90° per un monitor messo in verticale).",
  "colonna:Layout": "Come si divide lo schermo (slide, orologio, code…). Ogni schermo può avere il suo; «Predefinito» usa quello standard per il suo orientamento.",
  "colonna:Totem: code e stampante": "La stampante dei biglietti di questo totem (Anagrafica Stampanti Ticket). Vuoto: come indicato nel layout.",
  "colonna:Se non c'è nulla in onda": "L'immagine o il video da mostrare quando non c'è nessuna promozione in onda, invece dello schermo nero.",
  ...SCHERMI,
};

const STATO = {
  "Allarmi attivi": "Manda un'email quando uno schermo resta scollegato.",
  "Dopo": "Dopo quanto tempo di scollegamento parte l'avviso (evita avvisi per brevi interruzioni).",
  "Solo negli orari di accensione": "Avvisa solo se lo schermo doveva essere acceso: di notte e nei giorni di chiusura non disturba.",
  "Avvisa anche quando torna in linea": "Manda un'altra email quando lo schermo torna a funzionare.",
  "pulsante:Apri lo storico allarmi": "Apre «Report & Log · Storico allarmi»: quando gli schermi si sono scollegati e per quanto.",
};

const MESSA_IN_ONDA = {
  "Raggruppa per": "Come riassumere i passaggi: per campagna, promozione, fornitore, contenuto, negozio, schermo o giorno.",
  "Campagna": "Mostra solo una campagna.",
  "Fornitore": "Mostra solo i contenuti di un fornitore (es. per mandargli il rapporto).",
  "Negozio": "Mostra solo un negozio.",
  "Solo il fornitore": "L'invio automatico comprende solo questo fornitore.",
  "Solo la campagna": "L'invio automatico comprende solo questa campagna.",
  "Solo il negozio": "L'invio automatico comprende solo questo negozio.",
};

const ATTESE = {
  "Periodo": "Su quanti giorni calcolare i tempi d'attesa.",
  "Reparto": "Mostra un solo reparto, o tutti.",
};

const REGISTRO = {
  "Utente": "Mostra solo le operazioni di un utente.",
  "Cerca": "Cerca nel testo delle operazioni (es. il nome di una promozione o di uno schermo).",
};

const STORICO = { "Schermo": "Mostra solo gli allarmi di uno schermo." };

const LISTINI = {
  "Nuovo listino": "Il nome del nuovo listino (es. «Banco salumi»): poi si compila riga per riga, da Excel o dal gestionale.",
  "pulsante:Crea": "Crea il listino: poi lo scegli nella zona «Listino» di un layout.",
  "pulsante:": "Apre il listino per modificarne le righe.",
};

const REPARTI = {
  "Nome della serie": "Il nome della serie di file audio (es. SALUMERIA): i file si chiamano SALUMERIA_27.mp3.",
  "esempio:Nome della serie": "Il nome della serie di file audio (es. SALUMERIA): i file si chiamano SALUMERIA_27.mp3.",
  "pulsante:Rinomina": "Cambia il nome della serie (i file restano collegati).",
  "pulsante:Elimina la serie": "Elimina la serie e tutti i suoi file audio.",
  "pulsante:Scegli file": "Carica i file audio dei numeri (anche un'intera cartella): il nome decide il numero.",
  "Nome": "Il nome del reparto, come compare sui monitor e sul totem (es. Salumeria).",
  "Colore": "Il colore del reparto sui monitor e sui pulsanti del totem.",
  "Testo": "Il colore della scritta sopra il colore del reparto.",
  "colonna:Nome": "Il nome del reparto, come compare sui monitor e sul totem.",
  "colonna:Colori": "Colore del reparto e colore della scritta.",
  "colonna:Ordine": "L'ordine dei reparti sui monitor e sul totem (il più basso per primo).",
  "colonna:Attivo": "Spento: il reparto non compare sul totem e non dà numeri.",
  "colonna:Ora": "Il numero chiamato adesso. Cambiandolo si imposta da dove ripartire.",
  "colonna:Annunci (mp3)": "La serie di file audio che annuncia i numeri di questo reparto.",
  "colonna:Bilancia / pulsantiera": "Il collegamento per chiamare i numeri da bilancia, tablet o pulsante.",
};

const TELEFONO = {
  "QR sul biglietto e pagina della coda attivi": "Stampa un QR sul biglietto: il cliente lo inquadra e segue la coda dal telefono, con l'avviso quando tocca a lui.",
  "Testo sotto il QR": "La frase stampata sotto il QR (es. «Segui la coda dal telefono»).",
  "Avvisa quando mancano": "Quante persone prima il telefono avvisa il cliente di avvicinarsi.",
};

const SEDI = {
  "Nome": "Il nome della nuova voce (insegna, sede o gruppo).",
  "Colore": "Il colore dell'insegna, usato nel pannello per riconoscerla.",
  "colonna:Insegna": "L'insegna del negozio: serve per pubblicare le campagne per insegna.",
  "colonna:IP del Totem Master": "L'IP fisso del Totem Master del negozio: tiene i turni delle code e legge i file dei plugin. Vuoto: le code le tiene il server.",
  "esempio:es. 192.168.1.70": "L'IP fisso del Totem Master del negozio. Vuoto: le code le tiene il server.",
};

const UTENTI = {
  "Nome utente": "Il nome con cui la persona accede al pannello.",
  "Password": "Almeno 10 caratteri. La persona potrà cambiarla.",
  "Ruolo": "Administrator: gestisce tutto l'account dell'azienda. User: contenuti, palinsesto e banco.",
  "colonna:Attivo": "Spento: l'utente non può più accedere (i suoi dati restano).",
  "pulsante:Nuova password": "Imposta una nuova password per questo utente.",
  "pulsante:Crea utente": "Crea l'utente con i dati indicati.",
  "*spunta": "Limita l'utente a questa sede: vedrà solo i suoi schermi. Nessuna spunta: vede tutta l'azienda.",
};

const EMAIL = {
  "Usa questo server per le email dell'azienda": "Le email dell'azienda (allarmi, rapporti) partono da questo server, con il vostro dominio.",
  "Server SMTP": "L'indirizzo del server di posta in uscita (es. smtp.miodominio.it): lo trovi nelle impostazioni della posta aziendale.",
  "Porta": "Di solito 587 (STARTTLS) o 465 (SSL/TLS).",
  "Sicurezza": "Come si protegge il collegamento: STARTTLS con la porta 587, SSL/TLS con la 465.",
  "Utente": "L'account con cui si accede al server di posta (di solito l'indirizzo email).",
  "Password": "La password dell'account di posta. Resta cifrata; lasciala vuota per non cambiarla.",
  "Mittente": "Come appare chi manda l'email (es. «Supermercati Esempio <avvisi@miodominio.it>»).",
  "esempio:a chi mandare la prova": "L'indirizzo che riceve l'email di prova.",
};

const ACCENSIONE = { "pulsante:＋ Nuovo orario": "Crea un nuovo orario di accensione (fasce per giorno e giorni di chiusura), da assegnare a negozi o schermi." };

const DOWNLOAD = {
  "Scarica solo nella fascia": "Gli schermi scaricano i file nuovi solo nella fascia oraria indicata (es. di notte), per non rallentare la rete del negozio.",
  "Dalle": "Inizio della fascia di download.",
  "Alle": "Fine della fascia di download (può essere il giorno dopo, es. 22:30 → 06:00).",
  "Velocità massima per schermo": "Limita la banda usata da ogni schermo mentre scarica.",
};

const ASPETTO = {
  "Posizione del logo": "Dove sta il logo nella pagina di accesso: piccolo in alto accanto al nome, sopra le righe di testo, oppure grande al centro.",
  "Altezza del logo": "L'altezza del logo in pixel (la larghezza segue le proporzioni).",
  "Mostra il nome accanto al logo": "Mostra il nome dell'applicazione in alto. Toglilo se il nome è già scritto nel logo.",
  "Mostra i disegni degli schermi": "I disegni di monitor e totem in basso a sinistra.",
  "Riquadro chiaro dietro al logo": "Di solito il logo sta direttamente sulla barra colorata del pannello. Accendilo solo se il logo è scuro e sulla barra non si vede.",
  "Allineamento": "Testi e logo allineati a sinistra o al centro della parte colorata.",
  "Riga": "Il testo di questa riga (vuota: non si mostra).",
  "Grandezza (px)": "La grandezza del testo della riga, in pixel.",
  "Stile": "Normale o grassetto.",
  "Colore del testo": "Il colore della riga.",
  "pulsante:＋ Riga di testo": "Aggiunge una riga di testo (al massimo 8).",
  "pulsante:Vedi la pagina di accesso salvata": "Mostra in un riquadro la pagina di accesso come è salvata adesso.",
  "Nome dell'applicazione": "Il nome della piattaforma: pagina di accesso, barra del pannello, titoli. Vale per tutti i clienti.",
  "Frase della pagina di accesso": "La frase sotto il nome nella pagina di accesso.",
  "Colore": "Il colore principale della pagina di accesso e della barra del pannello.",
  "Logo della pagina di accesso": "Il logo grande della pagina di accesso (PNG, JPEG o WebP, fino a 3 MB; meglio con fondo trasparente).",
  "Icona della barra": "Un'icona piccola e quadrata (ICO, SVG, PNG o JPG, meglio quadrata e almeno 64×64): compare nella barra in alto del pannello e nella scheda del browser, al posto del logo.",
  "pulsante:Togli l'icona": "Toglie l'icona: nella barra torna il logo della pagina di accesso.",
  "Logo": "Il logo della piattaforma (PNG, JPEG o WebP, fino a 3 MB; meglio con fondo trasparente).",
  "pulsante:Togli il logo": "Toglie il logo della piattaforma.",
  "pulsante:Chiaro": "Pannello con fondo chiaro.",
  "pulsante:Scuro": "Pannello con fondo scuro.",
  "pulsante:✓ Automatico": "Segue l'impostazione chiaro/scuro del computer.",
  "pulsante:Automatico": "Segue l'impostazione chiaro/scuro del computer.",
};

const LISTINI_EDITOR = {
  "colonna:Prodotto": "Il nome del prodotto come compare sullo schermo.",
  "colonna:Prezzo €": "Il prezzo, con la virgola (es. 12,90).",
  "colonna:Unità": "L'unità del prezzo (al kg, all'etto, al pezzo…): scegli o scrivi.",
  "colonna:Nota": "Una nota breve accanto al prodotto (es. OFFERTA, NOVITÀ).",
  "colonna:Visibile": "Spento: la riga resta nel listino ma non si mostra sullo schermo.",
  "pulsante:＋ Riga": "Aggiunge un prodotto in fondo al listino.",
  "pulsante:Salva il listino": "Salva le righe: gli schermi le mostrano entro un minuto.",
  "Indirizzo del CSV": "Se il gestionale pubblica il listino in un file CSV su internet, lo schermo lo rilegge da solo da qui.",
  "Rileggi ogni": "Ogni quanto si rilegge il CSV del gestionale.",
};

const ACCENSIONE_EDITOR = {
  "Nome": "Un nome per l'orario (es. «Orario negozi», «Orario estivo»).",
  "fascia:giorno": "I giorni della settimana in cui vale questa fascia (clic per scegliere o togliere).",
  "fascia:ora": "Da che ora a che ora gli schermi restano accesi in questa fascia.",
  "pulsante:＋ Fascia": "Aggiunge un'altra fascia oraria (es. il pomeriggio, o la domenica).",
  "pulsante:Lun–Sab": "Riempie le fasce con un orario tipico: lunedì–sabato 8–21, domenica 9–13.",
  "pulsante:Con pausa pranzo": "Riempie le fasce con un orario con la pausa pranzo (8–13 e 16–20:30).",
  "data": "Un giorno di chiusura (tutto il giorno spento): scegli la data e premi «Aggiungi».",
  "pulsante:Aggiungi": "Aggiunge la data scelta ai giorni di chiusura.",
  "pulsante:✕": "Toglie questa fascia o questa data.",
  "scelta:Insegne": "L'orario vale per tutti gli schermi dei negozi di questa insegna.",
  "scelta:Gruppi": "L'orario vale per tutti gli schermi di questo gruppo.",
  "scelta:Schermi": "L'orario vale per questo schermo (l'orario più preciso vince).",
  "pulsante:Salva l'orario": "Salva l'orario: gli schermi lo ricevono entro un minuto.",
  "pulsante:Crea l'orario": "Crea l'orario: gli schermi lo ricevono entro un minuto.",
  "pulsante:Modifica": "Apre l'orario per cambiarlo.",
  "pulsante:Elimina": "Elimina l'orario: gli schermi interessati resteranno sempre accesi.",
};

const CLIENTI = {
  "Nome": "Il nome dell'azienda cliente, come compare nel pannello.",
  "Ragione sociale": "La ragione sociale dell'azienda (facoltativa).",
  "Partita IVA": "La partita IVA dell'azienda (facoltativa).",
  "Nome utente": "Il nome con cui il primo Administrator dell'azienda accede al pannello.",
  "Password": "La password del primo Administrator: almeno 10 caratteri. Potrà cambiarla.",
  "pulsante:Crea cliente": "Crea l'azienda e il suo primo Administrator.",
  "colonna:Attivo": "Spento: gli utenti dell'azienda non accedono più e gli schermi smettono di aggiornarsi (i dati restano).",
  "pulsante:Apri": "Lavora nel pannello di questa azienda.",
  "pulsante:Abilitazioni": "Cosa concedere all'azienda: numero di monitor e utenti, spazio, e cosa può gestire il suo Administrator.",
  "Monitor max": "Quanti schermi può abbinare l'azienda.",
  "Utenti max": "Quanti utenti può avere l'azienda.",
  "Spazio": "Lo spazio per i contenuti (immagini, video) dell'azienda, in MB.",
  "L'Administrator gestisce gli utenti": "L'Administrator dell'azienda può creare e modificare i suoi utenti.",
  "…i monitor": "L'Administrator può abbinare, rinominare e rimuovere gli schermi.",
  "…i layout": "L'Administrator può creare e modificare i layout grafici.",
  "Plugin Info Prezzo": "Concede il plugin Info Prezzo (lettore di codici a barre) all'azienda.",
  "Plugin Info Ingredienti": "Concede il plugin Info Ingredienti (etichette della bilancia) all'azienda.",
};

const PER_SCHEDA = {
  info_prezzo: PLUGIN, info_ingredienti: PLUGIN, stampanti: STAMPANTI, layout_ticket: TICKET, monitor: SCHERMI_TUTTI,
  stato: STATO, messa_in_onda: MESSA_IN_ONDA, attese: ATTESE, registro: REGISTRO, storico_allarmi: STORICO, listini: { ...LISTINI, ...LISTINI_EDITOR },
  reparti: REPARTI, clienti: CLIENTI, telefono: TELEFONO, sedi: SEDI, utenti: UTENTI, email: EMAIL, accensione: { ...ACCENSIONE, ...ACCENSIONE_EDITOR }, download: DOWNLOAD,
  aspetto: ASPETTO,
};

// La chiave di un controllo: la sua etichetta, il testo del pulsante, l'intestazione della
// colonna (nelle tabelle) o il testo di esempio.
export function chiaveDi(el) {
  const label = el.closest("label");
  if (label) {
    const span = label.classList.contains("campo") ? label.querySelector(":scope > span") : null;
    const testo = (span ? span.textContent : label.textContent).trim().replace(/^[★✓]\s*/, "");
    if (testo) return testo;
  }
  // Orari di accensione: i giorni e le ore di ogni fascia; i pulsanti di scelta con un titolo accanto.
  if (el.closest(".fascia")) return el.tagName === "BUTTON" ? "fascia:giorno" : "fascia:ora";
  const titolo = el.parentElement?.classList.contains("riga") ? el.parentElement.querySelector(":scope > span.etichetta") : null;
  if (titolo && el.tagName === "BUTTON") return `scelta:${titolo.textContent.trim()}`;
  if (el.tagName === "BUTTON") {
    const testo = el.textContent.trim();
    if (testo) return `pulsante:${testo}`;
  }
  const cella = el.closest("td");
  const tabella = cella?.closest("table");
  if (cella && tabella) {
    const th = tabella.querySelectorAll("thead th")[cella.cellIndex];
    if (th?.textContent.trim()) return `colonna:${th.textContent.trim()}`;
  }
  if (el.placeholder) return `esempio:${el.placeholder}`;
  const aria = el.getAttribute("aria-label");
  if (aria && !aria.includes("pixel")) return aria;
  if (el.tagName === "SELECT" && el.options.length) return `scelta:${el.options[0].textContent.trim()}`;
  if (el.getAttribute("aria-label")?.includes("pixel")) return "pixel";
  return el.type === "date" ? "data" : "";
}

function cerca(mappa, chiave) {
  if (!mappa || !chiave) return null;
  if (mappa[chiave]) return mappa[chiave];
  const k = Object.keys(mappa).filter((x) => chiave.startsWith(x)).sort((a, b) => b.length - a.length)[0];
  return k ? mappa[k] : null;
}

function applica(radice, mappa) {
  for (const el of radice.querySelectorAll("input, select, textarea, button")) {
    if (el.closest("[data-aiuto]") || el.title) continue;
    let chiave = chiaveDi(el);
    if (!chiave && el.type === "file") chiave = "file";
    if (!chiave && el.tagName === "SELECT") chiave = "scelta";
    const testo = cerca(mappa, chiave) || cerca(GENERALI, chiave) || (el.type === "checkbox" && mappa?.["*spunta"]) || null;
    if (!testo) continue;
    (el.closest("label") || el).dataset.aiuto = testo;
  }
}

// Osserva il contenuto del pannello e mette le spiegazioni ai controlli della scheda aperta.
export function osservaAiuti(contenuto, schedaAperta) {
  let attesa = null;
  new MutationObserver(() => {
    cancelAnimationFrame(attesa);
    attesa = requestAnimationFrame(() => applica(contenuto, PER_SCHEDA[schedaAperta()]));
  }).observe(contenuto, { childList: true, subtree: true });
}

// Per le altre pagine (es. l'editor dei layout): una sola tabella di spiegazioni.
export function osservaAiutiPagina(radice, mappa) {
  let attesa = null;
  const vai = () => applica(radice, mappa);
  new MutationObserver(() => {
    cancelAnimationFrame(attesa);
    attesa = requestAnimationFrame(vai);
  }).observe(radice, { childList: true, subtree: true });
  vai();
}

// La pagina «Creazione palinsesto»: i campi che non hanno già una spiegazione propria.
export const AIUTI_PALINSESTO = {
  "Nome della campagna": "Il nome che raggruppa le promozioni (es. l'anno o il tipo di offerte).",
  "pulsante:Crea la campagna": "Crea la campagna: poi aggiungi le promozioni con le loro date.",
  "pulsante:Salva la campagna": "Salva le modifiche alla campagna.",
  "pulsante:Importa": "Crea le promozioni dalle righe del file CSV scelto.",
  "pulsante:✕": "Chiude questa finestra.",
  "file": "Il file CSV (da Excel: «Salva con nome» → CSV) con una promozione per riga.",
  "pulsante:＋ Nuovo evento": "Crea un evento straordinario: un video o una diretta che in data e ora precise passa sopra a tutto il resto.",
  "Indirizzo di una lista": "L'indirizzo di una lista di canali (.m3u o .m3u8): si leggono i canali e si sceglie quale aggiungere.",
  "pulsante:Leggi la lista": "Legge la lista e mostra i canali che contiene.",
  "Indirizzo (.m3u8 o video)": "L'indirizzo della diretta (.m3u8) o di un video da trasmettere.",
  "Confermo che la riproduzione in pubblico": "La trasmissione in negozio di contenuti di terzi richiede i diritti (es. SIAE, licenze del canale): spunta per confermare di averli.",
};
