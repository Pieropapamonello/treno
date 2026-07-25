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

## Come impostare il treno (comandi Telegram)

Ci sono due modi per impostare quale treno seguire per una chat/gruppo:

- Comando diretto: usa il comando `/settrain` seguito dal numero del treno. Esempi:

```text
/settrain 8807          # imposta il treno 8807 immediatamente
/settrain               # il bot chiederà di inviare il numero del treno
```

Se invii `/settrain` senza argomenti, il bot imposterà la chat in modalità "attendo numero"; il messaggio successivo che contiene un numero verrà preso come nuovo treno.

- Menu: usa il comando `/menu` (o il pulsante Menu nel bot) per visualizzare la tastiera con i pulsanti. Premi `✏️ Imposta treno` per impostare il treno tramite interazione guidata.

Quando il treno è impostato per una chat, la configurazione è salvata separatamente per ogni chat in `train_state.json` (campo `chats`).

## Comandi Telegram disponibili

- `/settrain [numero]` — imposta il treno per la chat corrente.
- `/menu` — apre la tastiera con pulsanti rapidi (Aggiorna ora, Ultimo stato, Imposta treno, Aiuto).
- `/check` — richiede un aggiornamento immediato (puoi forzare con `?force=true` se richiesto via HTTP).
- `/status` — mostra l'ultimo stato salvato per la chat.
- `/help` — mostra la guida.

## Come settare il webhook e i comandi (esempi)

Esempio PowerShell per ottenere informazioni webhook:

```powershell
$token = "<TELEGRAM_BOT_TOKEN>"
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo" | ConvertTo-Json -Depth 10
```

Esempio per registrare i comandi del bot (usato anche dallo script `notify_train.register_bot_commands()`):

```bash
curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setMyCommands" -H "Content-Type: application/json" -d '{"commands":[{"command":"settrain","description":"Imposta il treno da seguire"},{"command":"menu","description":"Apri il menu dei pulsanti"},{"command":"check","description":"Controlla lo stato del treno ora"},{"command":"status","description":"Mostra l\'ultimo stato salvato"},{"command":"help","description":"Mostra la guida del bot"}]}'
```

Esempio per impostare il webhook (sostituisci l'URL con quello del tuo servizio su Render):

```bash
curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" -d "url=https://<your-render-service>.onrender.com/telegram_webhook"
```

Oppure in PowerShell:

```powershell
$token = "<TELEGRAM_BOT_TOKEN>"
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/setWebhook" -Method Post -Body @{ url = "https://<your-render-service>.onrender.com/telegram_webhook" }
```

## Variabili d'ambiente importanti

- `TELEGRAM_BOT_TOKEN` — token del bot Telegram (mai committare questo valore).
- `TELEGRAM_CHAT_ID` — chat di default per inviare notifiche (opzionale se usi bot in chat specifiche).
- `TRAIN_URL` — URL della pagina di Trenitalia per il treno (opzionale; il servizio crea l'endpoint REST automaticamente).
- `TRAIN_LABEL` — numero del treno di default.
- `SEND_ONLY_ON_CHANGE` — se `true` (default) invia messaggi solo quando lo stato cambia.
- `START_SCHEDULER` — se `true` (default) avvia il controllo automatico interno.
- `STATE_FILE_PATH` — percorso per `train_state.json` (se Render non offre persistenza, considera un DB esterno).

## Scheduler interno e `gunicorn`

Il servizio include un scheduler in background che controlla periodicamente lo stato dei treni salvati in `train_state.json`.

- `START_SCHEDULER=true` abilita il scheduler.
- In `gunicorn`, per evitare controlli duplicati, il scheduler parte solo se `GUNICORN_WORKER_ID` è `1`.
- Se usi più worker, imposta il primo worker con `GUNICORN_WORKER_ID=1` e disabilita il scheduler sugli altri worker.

## Pulsanti Telegram aggiuntivi

Il menu include ora:

- `⏱ Frequenza` — imposta l'intervallo in minuti per i controlli automatici (default 1 minuto).
- `🔕 Disattiva notifiche` — disattiva le notifiche automatiche per il treno corrente.
- `🔔 Riattiva notifiche` — riattiva le notifiche e resetta lo stato di arrivo.

Quando il treno è segnalato come `arrivato`, il bot disattiva automaticamente le notifiche per quella chat e non invia altri messaggi automatici.

## Persistenza e Render

Il file `train_state.json` viene salvato nel filesystem dell'applicazione. Su Render il filesystem è in genere effimero tra deploy; se vuoi che la configurazione e lo stato sopravvivano ai deploy/ridimensionamenti, valuta una soluzione con storage persistente (ad es. un bucket S3, un piccolo DB come Redis o Postgres, o Render Persistent Disks se disponibile).

## Sicurezza e git

- NON committare mai `train_state.json` o il token del bot nel repository. Aggiungi `train_state.json` al `.gitignore` se non già presente.
- Le variabili segrete devono essere gestite tramite l'interfaccia di Render (Environment > Add Environment Variable).

## Esempio rapido: cambiare treno dalla chat

1. In chat privata o nel gruppo scrivi:

```text
/settrain 1234
```

Il bot risponderà confermando il nuovo treno. In alternativa:

1. Scrivi `/menu`.
2. Premi `✏️ Imposta treno`.
3. Invia il numero del treno come messaggio successivo.

---

Per altri dettagli tecnici, vedi `notify_train.py` e lo script di setup per Telegram se presente.

## Nota sugli orari e il ritardo

Le notifiche mostrano gli orari rilevati e, quando disponibile, indicano anche il ritardo tra parentesi. Ad esempio:

```
🛬 Arrivo previsto a Taranto alle 15:30 (+10 min)
```

Questo significa che l'orario visualizzato è l'orario previsto e che il treno ha un ritardo di 10 minuti. Se è disponibile l'orario effettivo di arrivo verrà mostrato allo stesso modo con il ritardo se presente.
