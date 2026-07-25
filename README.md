# Train Telegram Notifier

Questo progetto invia aggiornamenti Telegram per un treno Trenitalia.

## Struttura del repo

- `notify_train.py` — script che controlla lo stato del treno e invia messaggi solo quando cambia lo stato o arriva a destinazione.
- `requirements.txt` — dipendenze Python.
- `render.yaml` — configurazione Render cron service.
- `train_state.json` — file di stato persistente creato dall'app in runtime.

## Come usare su GitHub + Render

1. Carica questa cartella su un repository GitHub.
2. Crea un nuovo servizio su Render come Web Service.
3. Assicurati che Render usi Python 3.12.
4. Imposta queste variabili d'ambiente su Render:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TRAIN_URL` (opzionale, default is the Trenitalia train page URL)
   - `TRAIN_LABEL` (opzionale, default `8807`)
   - `SEND_ONLY_ON_CHANGE` (opzionale, default `true`)
   - `STATE_FILE_PATH` (opzionale, default `train_state.json`)

### Esempio `TRAIN_URL`
Usa l'URL della pagina Trenitalia per il treno:

```text
http://www.viaggiatreno.it/infomobilitamobile/pages/cercaTreno/cercaTreno.jsp?treno=8807&origine=S01700&datapartenza=1784930400000
```

Il servizio genera automaticamente l'endpoint REST interno per `andamentoTreno` dal valore di `TRAIN_URL`.

## Esecuzione

Render esegue il servizio come web app usando:

```bash
gunicorn notify_train:app --bind 0.0.0.0:$PORT
```

## Endpoint disponibili

- `/` — conferma che il servizio è attivo.
- `/check` — lancia un test di stato e invia un messaggio Telegram se necessario.
- `/status` — mostra l'ultimo stato salvato.

## Note

- Lo script salva l’ultimo stato del treno in `train_state.json`.
- Viene inviato un messaggio Telegram solo se cambia lo stato, cambia il ritardo, o arriva a Taranto.
- Se vuoi forzare il controllo anche senza cambio di stato, usa `/check?force=true`.
