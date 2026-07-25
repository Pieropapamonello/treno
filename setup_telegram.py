import os, requests, json

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
if not TOKEN or not APP_URL:
    raise SystemExit("Imposta TELEGRAM_BOT_TOKEN e APP_URL nelle env prima di eseguire")

cmds = {"commands":[
  {"command":"settrain","description":"Imposta il treno da seguire"},
  {"command":"check","description":"Controlla lo stato del treno ora"},
  {"command":"status","description":"Mostra l’ultimo stato salvato"},
  {"command":"help","description":"Mostra la guida del bot"}
]}

r = requests.post(f"https://api.telegram.org/bot{TOKEN}/setMyCommands", json=cmds, timeout=10)
print("setMyCommands:", r.status_code, r.text)

r2 = requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", data={"url": f"https://{APP_URL}/telegram_webhook"}, timeout=10)
print("setWebhook:", r2.status_code, r2.text)
