# Riordino deterministico delle tracce journey — design spec

Status: in design.
Scope: bounded/architettonico leggero — nuova funzione in un modulo esistente
(`backend/playlist_ordering.py`), un nuovo punto di chiamata in una funzione esistente
(`_generate_from_journey_playlist` in `main.py`), nessun nuovo endpoint, nessuna nuova
tabella dati.

## Motivazione

Il rafforzamento del prompt journey (`_journey_instruction`, 2026-08-25) chiede all'AI di
costruire una sequenza che converge in modo monotono verso la canzone finale. Verifiche
live su tre generazioni reali (due con Gemini in fallback per quota esaurita, una con
`gemini-3.7-flash` via OpenRouter, quindi non un problema di modello debole) mostrano che
anche un modello capace non rispetta in modo affidabile questo vincolo su liste di
15-20 tracce: la "vicinanza" alla canzone finale non è qualcosa che un LLM riesce ad
auto-verificare in modo rigoroso lungo tutta la sequenza. Coerentemente con il principio
già presente nel codice ("l'output dell'LLM non viene mai fidato per vincoli esatti — viene
sempre validato/applicato in modo deterministico dopo la chiamata AI", vedi
`policy_enforcement.py`/`metadata_validation.py` per anno/paese/quota), questa spec applica
lo stesso principio all'ordine delle tracce journey.

## Vincolo di design ereditato dalla spec originale

`docs/superpowers/specs/2026-08-25-track-journey-design.md`, sezione "Explicitly out of
scope", scarta esplicitamente l'uso delle sole feature audio ReccoBeats
(energy/valence/danceability/...) come meccanismo di bridging: un confronto live ha
mostrato output genre-incoherent, con un esempio concreto di un brano K-pop dal profilo
audio quasi identico a un brano French-house completamente scorrelato per genere/cultura.
Le feature audio da sole **non catturano l'identità di genere**.

Questa spec non ripropone quell'approccio: usa i **tag community di Last.fm come segnale
primario** (già usati con lo stesso ruolo — segnale primario, ReccoBeats come raffinamento
secondario solo su casi ambigui — nel meccanismo di creative-fit esistente in
`backend/creative_intent.py::_assess_creative_fit_fresh`), e le feature ReccoBeats
solo come criterio di ordinamento fine **dentro** un gruppo già compatibile per genere,
mai per scavalcare un confine di genere.

## Infrastruttura riusata (nessuna nuova dipendenza esterna)

- `backend/lastfm_tags.py::tag_evidence_for_tracks(tracks) -> list[LastfmTagEvidence]` —
  fetch batch dei tag community per traccia (fino a `MAX_TRACK_TAGS=8` per traccia, cache
  6h, concorrenza già limitata a `MAX_CONCURRENT_REQUESTS=8`). `LastfmTagEvidence.available`
  è `True` solo se `track_tags` è non vuoto.
- `backend/reccobeats_features.py::audio_evidence_for_track(artist, title) ->
  ReccoBeatsAudioEvidence` — stesso meccanismo già usato da
  `playlist_ordering.py::order_tracks_by_energy` (fetch concorrente con
  `asyncio.wait(..., timeout=_ENERGY_FETCH_BUDGET_SECONDS)`, task pendenti cancellati e
  trattati come evidenza vuota). Di questa dataclass uso solo le 7 dimensioni già su scala
  [0,1] comparabile: `danceability, energy, valence, liveness, acousticness,
  instrumentalness, speechiness` — escludo `tempo` (BPM) e `loudness` (dB), che
  richiederebbero soglie di normalizzazione arbitrarie senza precedente nel codice.
- `backend/text_normalization.py::normalize_identity(value) -> str` — normalizzazione
  già usata altrove per confronti fuzzy (casefold, rimozione accenti/punteggiatura);
  la riuso per confrontare i tag in modo insensibile a maiuscole/punteggiatura
  (es. "K-Pop" e "k pop" devono contare come lo stesso tag).

## Algoritmo

Nuova funzione `order_journey_tracks_by_proximity(start, middle_tracks, end) -> list[dict]`
in `backend/playlist_ordering.py`. `start`/`end` sono i payload (dict) delle due tracce
anchor già costruiti da `_generate_from_journey_playlist` prima di questa chiamata;
`middle_tracks` è `result["tracks"]` (il bridge restituito da `_anchored_other_tracks`,
non ancora concatenato con gli anchor).

**1. Fetch.** Se `len(middle_tracks) < 2`, nessun riordino possibile/utile: ritorna
`middle_tracks` invariato. Altrimenti, fetch concorrente (in parallelo tra loro, non
sequenziale) di:
- tag evidence per `start`, `end`, e ogni traccia intermedia (`tag_evidence_for_tracks`
  su tutte le tracce in un'unica chiamata batch)
- audio evidence per `start`, `end`, e ogni traccia intermedia (stesso pattern di
  `order_tracks_by_energy`: task concorrenti, budget `_ENERGY_FETCH_BUDGET_SECONDS`,
  task pendenti cancellati e trattati come evidenza vuota)

Se `end` non ha **né** tag evidence **né** audio evidence disponibili: skip totale,
`middle_tracks` invariato (senza un riferimento sull'anchor finale non c'è nulla su cui
far convergere l'ordine).

**2. Definizioni.**
- `tag_set(track) = {normalize_identity(tag) for tag in evidence.track_tags}` (insieme
  vuoto se evidence non disponibile).
- `tag_compatible(A, B)`: `True` se `A` o `B` non ha evidence (dato mancante non blocca
  mai — stesso principio "fail open" già usato in tutto il codice per gli arricchimenti
  opzionali), altrimenti `True` se `tag_set(A) & tag_set(B)` non è vuoto.
- `closeness(track)`: se sia `track` che `end` hanno tag evidence,
  `len(tag_set(track) & tag_set(end))`; altrimenti `None` (sconosciuto).
- `audio_distance(A, B)`: se entrambe hanno almeno una dimensione delle 7 in comune,
  distanza euclidea sulle dimensioni condivise, normalizzata per `sqrt(n_dimensioni)`;
  altrimenti `None`.

**3. Greedy vincolato**, un passo per ogni slot intermedio da riempire, `prev` inizializzato
a `start`:
1. **Tier A (compatibilità di genere)**: tra le tracce non ancora piazzate, tengo quelle
   con `tag_compatible(prev, candidate) == True`.
2. **Tier A2 (convergenza)**: se `closeness(prev)` è noto, restringo ulteriormente a
   `closeness(candidate) >= closeness(prev)`. Se questo svuota il pool, ignoro questo
   sotto-filtro per il passo corrente (la convergenza è una preferenza direzionale, non
   una garanzia di sicurezza di genere) e mantengo il pool del Tier A.
3. Se il Tier A stesso è vuoto (nessuna traccia rimasta condivide un tag con `prev`,
   pur avendo entrambe dati reali) — caso limite raro — abbandono il vincolo di genere
   per il resto dell'algoritmo da questo punto in poi e procedo scegliendo tra tutte le
   tracce rimaste solo in base alla vicinanza audio a `prev` (punto 4), piuttosto che
   fallire.
4. **Tier B (ordinamento fine)**: tra i sopravvissuti del Tier A/A2, scelgo quello con
   `audio_distance(candidate, prev)` minima. Se nessun sopravvissuto ha audio evidence
   disponibile, mantengo l'ordine relativo originale tra i sopravvissuti (tie-break
   stabile).
5. La traccia scelta diventa il nuovo `prev`, si passa allo slot successivo.

**4. Tracce senza alcuna evidence** (né tag né audio) mantengono il loro slot originale
nella sequenza intermedia; le altre si ricompongono per riempire gli slot restanti —
stesso pattern "slot preservato" già usato da `order_tracks_by_energy`
(`matched_indices`/`result[slot] = track`).

**5. Reason.** Dopo il riordino, rimuovo il campo `reason` da ogni traccia intermedia
(non più garantito coerente col nuovo vicino). Resta invariato sulle due tracce anchor
(testo fisso, non riferito ai vicini).

## Punto di integrazione

In `_generate_from_journey_playlist()` (`main.py:1651`), dopo la costruzione di
`start_payload`/`end_payload` (righe 1697-1708) e prima della concatenazione finale
(riga 1710):

```python
result["tracks"] = await order_journey_tracks_by_proximity(
    start_payload, result["tracks"], end_payload
)
result["tracks"] = [start_payload, *result["tracks"], end_payload]
```

## Performance

Le due fetch (tag + audio) partono in parallelo tra loro via `asyncio.gather`, non in
sequenza — stesso principio già usato per `start_evidence`/`end_evidence` poco sopra
nella stessa funzione. Nessun nuovo budget/costante di timeout: ognuna delle due fetch
riusa i propri limiti già collaudati (`_ENERGY_FETCH_BUDGET_SECONDS` per l'audio,
`MAX_CONCURRENT_REQUESTS` per i tag). Da verificare con un confronto reale
prima/dopo (vedi memoria progetto "Generation speed priority" — la latenza è sempre
prioritaria): questo aggiunge un round-trip di rete per traccia rispetto al percorso
journey attuale, che già non fa fetch di feature per le tracce del bridge.

## Test previsti

- `tag_compatible`/`closeness`/`audio_distance`: casi con evidence completa, parziale
  (una traccia sola con dati), assente per entrambe.
- Greedy vincolato su un caso sintetico noto: verificare che la sequenza risultante non
  piazzi mai adiacenti due tracce con tag reali e completamente disgiunti quando esistono
  alternative compatibili, e che `closeness` sia non-decrescente quando i dati lo
  permettono.
- Degradazione: `end` senza alcuna evidence (no-op), alcune tracce intermedie senza
  evidence (mantengono slot), Tier A che si svuota (fallback a solo audio).
- Rimozione del `reason` post-riordino sulle sole tracce intermedie.
- Integrazione end-to-end su `_generate_from_journey_playlist` con Last.fm e ReccoBeats
  mockati (nessuna chiamata di rete reale nei test).

## Fuori scope

- Nessuna modifica al percorso `energy_ordering`/`chronological_ordering` esistente
  (`main.py:1251-1284`): il journey continua a non attraversarlo, come da design
  originale (wording del prompt deliberatamente privo di vocabolario che lo attiverebbe).
- Nessuna nuova chiamata AI per il riordino: è deterministico, coerente con l'obiettivo
  di non dipendere più dalla sola formulazione del prompt.
- Nessuna modifica alla UI: il riordino è trasparente lato client, cambia solo l'ordine
  e la presenza del `reason` sulle tracce intermedie già gestiti dal rendering esistente.
