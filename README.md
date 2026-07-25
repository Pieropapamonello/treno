# Train Telegram Notifier

Questo progetto invia aggiornamenti Telegram per un treno Trenitalia.

## Struttura del repo

- `notify_train.py` — script che controlla lo stato del treno e invia messaggi solo quando cambia lo stato o arriva a destinazione.
- `requirements.txt` — dipendenze Python.
- `render.yaml` — configurazione Render cron service.
- `train_state.json` — file di stato persistente creato dall'app in runtime.

## Come usare su GitHub + Render

1. Carica questa cartella su un repository GitHub.
2. Crea un nuovo servizio su Render configurato come cron job.
3. Assicurati che Render usi Python 3.12.
4. Imposta queste variabili d'ambiente su Render:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TRAIN_URL` (opzionale)
   - `TRAIN_LABEL` (opzionale)
   - `SEND_ONLY_ON_CHANGE` (opzionale, default `true`)
   - `STATE_FILE_PATH` (opzionale, default `train_state.json`)

## Esecuzione

Render esegue il servizio ogni 10 minuti usando `python notify_train.py`.

## Note

- Lo script salva l’ultimo stato del treno in `train_state.json`.
- Viene inviato un messaggio Telegram solo se cambia lo stato, cambia il ritardo, o arriva a Taranto.
- Se preferisci, puoi togliere `SEND_ONLY_ON_CHANGE=true` per inviare un messaggio a ogni esecuzione.
