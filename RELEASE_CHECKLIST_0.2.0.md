# PlaylistMuse 0.2.0 — Release validation checklist

Questa checklist deve essere completata sulla branch `beta` prima di proporre il passaggio a `main` e la pubblicazione dell'immagine Docker `latest`.

## Criteri bloccanti

La release non è promuovibile se si verifica anche una sola delle seguenti condizioni:

- test automatici, container o Chromium non superati;
- bug che impedisce generazione, sostituzione o pubblicazione;
- perdita di configurazione dopo il riavvio del container;
- regressioni nel rispetto dei vincoli espliciti;
- duplicati o versioni live, cover o remix non richieste;
- modifica grafica involontaria;
- credenziali esposte nei log o in risposte API;
- versione applicativa non coerente con la release;
- aggiornamento da una precedente installazione non verificato.

## Validazione automatica

- [ ] compilazione di backend, test e script;
- [ ] Ruff senza errori;
- [ ] suite Python completa;
- [ ] sintassi e test JavaScript;
- [ ] validazione di `docker-compose.yml`;
- [ ] build dell'immagine Docker;
- [ ] avvio e health check del container;
- [ ] caricamento home, pagina playlist e asset principali;
- [ ] controlli di validazione delle API;
- [ ] salvataggio configurazione AI e onboarding;
- [ ] riavvio del container con verifica della persistenza;
- [ ] permessi privati dei file contenenti configurazioni;
- [ ] test Chromium desktop e viewport mobile;
- [ ] verifica UI di `Simple`, `Clarity: Excellent` e `Clarity: Good`;
- [ ] rendering della playlist, dettagli traccia, modifica titolo e mosaico.

## Installazione e aggiornamento

- [ ] installazione pulita usando l'immagine `beta`;
- [ ] onboarding mostrato una sola volta;
- [ ] configurazioni conservate dopo `docker compose down` e successivo avvio;
- [ ] aggiornamento di una precedente installazione mantenendo `data/`;
- [ ] nessun errore di permessi sul volume persistente;
- [ ] README sufficiente per installare e aggiornare senza informazioni esterne.

## Configurazione AI

Eseguire almeno un test completo con il provider destinato all'uso reale e un controllo delle altre modalità configurabili.

- [ ] salvataggio, attivazione e disconnessione del provider;
- [ ] chiave di un provider diverso rifiutata;
- [ ] modello primario e fallback conservati;
- [ ] OpenRouter Auto e Free condividono correttamente la chiave;
- [ ] Ollama o endpoint custom funzionano con URL configurato;
- [ ] errore comprensibile con provider non raggiungibile;
- [ ] nessuna chiave completa esposta nella UI, nelle API o nei log.

## Analisi del prompt

Provare richieste in italiano, inglese e almeno un'altra lingua supportata.

- [ ] richiesta semplice classificata `Simple`;
- [ ] richiesta articolata classificata coerentemente;
- [ ] colore della complessità da verde a rosso al crescere del punteggio;
- [ ] `Clarity: Excellent` senza dettaglio aggiuntivo;
- [ ] `Clarity: Good` senza dettaglio aggiuntivo;
- [ ] ambiguità reali mostrate solo con chiarezza inferiore;
- [ ] progressioni energetiche e strutture riconosciute in modo generale;
- [ ] stessa logica applicata indipendentemente dalla lingua del prompt.

## Generazione da prompt

Eseguire ogni scenario almeno due volte per individuare risultati instabili.

- [ ] richiesta semplice da 15 tracce;
- [ ] richiesta standard da 25 tracce;
- [ ] richiesta complessa con progressione energetica;
- [ ] intervallo temporale o anno esatto;
- [ ] lingua o provenienza geografica obbligatoria;
- [ ] numero massimo di brani per artista;
- [ ] brano o artista obbligatorio;
- [ ] esclusione di artista, genere o periodo;
- [ ] esclusione di live, cover e remix;
- [ ] nessun duplicato per titolo/artista o video ID;
- [ ] tutte le tracce risolvibili su YouTube Music;
- [ ] titolo, descrizione e motivazioni coerenti con il prompt;
- [ ] errore esplicito quando i vincoli non permettono di raggiungere il numero richiesto.

## Generazione da brano seme

- [ ] ricerca del brano seme;
- [ ] modalità `Strict` vicina al seme;
- [ ] modalità `Balanced` con variazioni controllate;
- [ ] modalità `Exploratory` più ampia ma musicalmente collegata;
- [ ] seme presente una sola volta e in prima posizione;
- [ ] nessun upload alternativo duplicato dello stesso brano;
- [ ] fallback Last.fm da traccia simile ad artista simile;
- [ ] comportamento comprensibile quando Last.fm non è disponibile.

## Sostituzione delle tracce

- [ ] sostituzione prima della pubblicazione;
- [ ] nuovo brano non duplicato;
- [ ] vincoli originali ancora rispettati;
- [ ] ruolo musicale della traccia preservato;
- [ ] cronologia locale della sostituzione coerente;
- [ ] mosaico aggiornato senza alterare le immagini delle altre tracce;
- [ ] sostituzione disabilitata dopo la pubblicazione.

## Last.fm

- [ ] chiave valida salvata e riconosciuta;
- [ ] chiave non valida rifiutata;
- [ ] disconnessione completa;
- [ ] generazione da prompt con anchor AI;
- [ ] generazione da seme con `track.getSimilar`;
- [ ] fallback `artist.getSimilar` verificato;
- [ ] diagnostica di anchor, segnali, strategie e artisti rappresentati corretta;
- [ ] timeout o indisponibilità non bloccano in modo permanente l'app.

## YouTube Music

Usare una playlist di test ed eliminare i dati creati al termine.

- [ ] salvataggio credenziali OAuth;
- [ ] connessione tramite device flow;
- [ ] stato e account visualizzati correttamente;
- [ ] pubblicazione privata;
- [ ] pubblicazione non in elenco;
- [ ] pubblicazione pubblica;
- [ ] ordine delle tracce conservato;
- [ ] numero di tracce pubblicate uguale alla playlist locale;
- [ ] mosaico 2×2 caricato come immagine della playlist;
- [ ] fallimento del solo upload immagine restituisce un avviso senza perdere la playlist;
- [ ] refresh del token verificato;
- [ ] retry del solo errore transitorio previsto verificato;
- [ ] disconnessione e nuova connessione riuscite;
- [ ] errore quota o rete mostrato senza dati incoerenti.

## Prestazioni e stabilità

- [ ] generazione da 15, 25 e 50 tracce senza blocchi dell'interfaccia;
- [ ] nessuna crescita anomala della memoria dopo più generazioni;
- [ ] annullamento o errore non lascia pulsanti in stato di caricamento;
- [ ] doppio click non avvia operazioni duplicate;
- [ ] riapertura della pagina dopo un errore ripristina uno stato utilizzabile;
- [ ] log del container privi di traceback non gestiti durante i flussi normali.

## Compatibilità visiva e browser

Non sono previste modifiche grafiche per questa release.

- [ ] Chrome desktop;
- [ ] Chrome su Pixel o viewport equivalente;
- [ ] nessun overflow orizzontale;
- [ ] finestre impostazioni utilizzabili;
- [ ] focus da tastiera e tasto Escape funzionanti;
- [ ] nessun errore JavaScript nella console;
- [ ] nessuna regressione rispetto agli screenshot approvati.

## Preparazione della stable

Da eseguire solo dopo il completamento dei test precedenti:

- [ ] correggere la versione interna da `0.7.0` a `0.2.0`;
- [ ] aggiornare note di rilascio e riferimenti alla beta;
- [ ] aprire una PR da `beta` a `main` senza merge automatico;
- [ ] verificare nuovamente CI e release validation sulla PR;
- [ ] controllare il diff finale per escludere modifiche non previste;
- [ ] ottenere approvazione esplicita prima del merge su `main`;
- [ ] pubblicare `0.2.0` e aggiornare Docker `latest` solo dopo il merge approvato.

## Esito

- Stato: **non ancora approvata**
- Bug bloccanti aperti: _da compilare_
- Test manuali completati da: _da compilare_
- Data validazione: _da compilare_
- Approvazione al merge su `main`: _necessaria e separata_
