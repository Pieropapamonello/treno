import json
import os
import re
import requests
import logging
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from flask import Flask, jsonify, request
from bs4 import BeautifulSoup

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

DEFAULT_TRAIN_URL = "http://www.viaggiatreno.it/infomobilitamobile/pages/cercaTreno/cercaTreno.jsp?treno=8807&origine=S01700&datapartenza=1784930400000"
TRAIN_URL = os.getenv("TRAIN_URL", DEFAULT_TRAIN_URL)
TRAIN_LABEL = os.getenv("TRAIN_LABEL", "8807")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE_PATH = os.getenv("STATE_FILE_PATH", "train_state.json")
SEND_ONLY_ON_CHANGE = os.getenv("SEND_ONLY_ON_CHANGE", "true").lower() in {"1", "true", "yes", "on"}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# basic logging for debugging webhook/commands
logging.basicConfig(level=logging.INFO)


def format_millis(timestamp_ms):
    if timestamp_ms is None:
        return None
    try:
        ts = int(timestamp_ms) / 1000.0
    except (TypeError, ValueError):
        return None
    if ROME_TZ is not None:
        return datetime.fromtimestamp(ts, tz=ROME_TZ).strftime("%H:%M")
    return datetime.utcfromtimestamp(ts).strftime("%H:%M")


def build_rest_api_url(train_url):
    if "/resteasy/viaggiatreno/andamentoTreno/" in train_url:
        return train_url

    parsed = urlparse(train_url)
    params = parse_qs(parsed.query)
    if "treno" in params and "origine" in params and "datapartenza" in params:
        numero_treno = params["treno"][0]
        origine = params["origine"][0]
        data_partenza = params["datapartenza"][0]
        base = f"{parsed.scheme}://{parsed.netloc}"
        if "/pages/" in parsed.path:
            prefix = parsed.path.split("/pages/", 1)[0]
        else:
            prefix = parsed.path.rsplit("/", 1)[0]
        return f"{base}{prefix}/resteasy/viaggiatreno/andamentoTreno/{origine}/{numero_treno}/{data_partenza}"
    return None


def fetch_train_page():
    response = requests.get(
        TRAIN_URL,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.text


def fetch_train_data():
    api_url = build_rest_api_url(TRAIN_URL)
    if api_url:
        response = requests.get(
            api_url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return response.text
    return fetch_train_page()


def parse_train_info_html(html):
    soup = BeautifulSoup(html, "html.parser")
    text = "\n".join(soup.stripped_strings)

    info = {
        "current_location": None,
        "current_time": None,
        "delay_minutes": None,
        "status": None,
        "destination": "Taranto",
        "destination_arrival_predicted": None,
        "destination_arrival_actual": None,
    }

    last_rilevamento = re.search(
        r"Ultimo rilevamento a\s+(.+?)\s+Ore\s*:\s*(\d{1,2}:\d{2})",
        text,
        re.IGNORECASE,
    )
    if last_rilevamento:
        info["current_location"] = last_rilevamento.group(1).strip()
        info["current_time"] = last_rilevamento.group(2)

    delay_match = re.search(r"ritardo di\s*(\d+)\s*min", text, re.IGNORECASE)
    if delay_match:
        info["delay_minutes"] = int(delay_match.group(1))

    status_match = re.search(r"il treno\s+(.+?)(?:\.|$)", text, re.IGNORECASE)
    if status_match:
        info["status"] = status_match.group(1).strip()

    predicted = re.search(r"Arrivo previsto\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    if predicted:
        info["destination_arrival_predicted"] = predicted.group(1)

    actual = re.search(r"Arrivo effettivo\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    if actual:
        info["destination_arrival_actual"] = actual.group(1)

    if info["status"] is None:
        lower_text = text.lower()
        if "in coda" in lower_text:
            info["status"] = "in coda"
        elif "in transito" in lower_text:
            info["status"] = "in transito"
        elif "arrivato" in lower_text:
            info["status"] = "arrivato"

    return info


def parse_train_info_json(data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return parse_train_info_html(data)

    info = {
        "current_location": None,
        "current_time": None,
        "delay_minutes": None,
        "status": None,
        "destination": data.get("destinazione") or "Taranto",
        "destination_arrival_predicted": None,
        "destination_arrival_actual": None,
    }

    info["delay_minutes"] = data.get("ritardo")
    info["status"] = "arrivato" if data.get("arrivato") else "in transito"

    fermate = data.get("fermate") or []
    if fermate:
        last_stop = fermate[-1]
        if last_stop.get("arrivoReale") is not None:
            info["destination_arrival_actual"] = format_millis(last_stop.get("arrivoReale"))
        elif last_stop.get("arrivo_teorico") is not None:
            info["destination_arrival_predicted"] = format_millis(last_stop.get("arrivo_teorico"))
        elif last_stop.get("programmata") is not None:
            info["destination_arrival_predicted"] = format_millis(last_stop.get("programmata"))

        last_reached = None
        for stop in reversed(fermate):
            if stop.get("arrivoReale") is not None or stop.get("partenzaReale") is not None:
                last_reached = stop
                break
        if last_reached:
            info["current_location"] = last_reached.get("stazione")
            info["current_time"] = format_millis(last_reached.get("arrivoReale") or last_reached.get("partenzaReale"))
        elif fermate[0].get("programmata") is not None:
            info["current_location"] = fermate[0].get("stazione")
            info["current_time"] = format_millis(fermate[0].get("programmata"))

    return info


def parse_train_info(data):
    if isinstance(data, dict):
        return parse_train_info_json(data)
    return parse_train_info_html(data)


def load_state():
    try:
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"Warning: cannot read state file: {exc}")
        return {}


def save_state(state):
    try:
        with open(STATE_FILE_PATH, "w", encoding="utf-8") as fp:
            json.dump(state, fp, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Warning: cannot save state file: {exc}")


def get_chat_key(chat_id):
    return str(chat_id)


def get_chat_state(chat_id):
    state = load_state()
    chats = state.setdefault("chats", {})
    return chats.setdefault(get_chat_key(chat_id), {})


def get_chat_config(chat_id):
    chat = get_chat_state(chat_id)
    return {
        "train_url": chat.get("train_url", TRAIN_URL),
        "train_label": chat.get("train_label", TRAIN_LABEL),
        "pending_action": chat.get("pending_action"),
    }


def set_chat_config(chat_id, train_label=None, train_url=None, pending_action=None):
    state = load_state()
    chats = state.setdefault("chats", {})
    chat = chats.setdefault(get_chat_key(chat_id), {})
    if train_label is not None:
        chat["train_label"] = train_label
    if train_url is not None:
        chat["train_url"] = train_url
    if pending_action is not None:
        chat["pending_action"] = pending_action
    elif "pending_action" in chat:
        chat.pop("pending_action", None)
    save_state(state)
    return chat


def build_resteasy_url_with_train(train_url, train_label):
    if "/resteasy/viaggiatreno/andamentoTreno/" in train_url:
        parsed = urlparse(train_url)
        path_parts = parsed.path.split("/")
        try:
            idx = path_parts.index("andamentoTreno")
            path_parts[idx + 2] = train_label
            new_path = "/".join(path_parts)
            return parsed._replace(path=new_path, query="", fragment="").geturl()
        except (ValueError, IndexError):
            pass

    parsed = urlparse(train_url)
    params = parse_qs(parsed.query)
    origine = params.get("origine", [None])[0]
    datapartenza = params.get("datapartenza", [None])[0]
    if origine and datapartenza:
        base = f"{parsed.scheme}://{parsed.netloc}"
        if "/pages/" in parsed.path:
            prefix = parsed.path.split("/pages/", 1)[0]
        else:
            prefix = parsed.path.rsplit("/", 1)[0]
        return f"{base}{prefix}/resteasy/viaggiatreno/andamentoTreno/{origine}/{train_label}/{datapartenza}"

    return None


def normalize_train_label(text):
    match = re.search(r"\d+", text)
    return match.group(0) if match else None


def fetch_train_page(train_url=None):
    if train_url is None:
        train_url = TRAIN_URL
    response = requests.get(
        train_url,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.text


def fetch_train_data(train_url=None, train_label=None):
    if train_url is None:
        train_url = TRAIN_URL
    api_url = build_rest_api_url(train_url)
    # if a specific train_label was requested, try to construct a REST URL for it
    if train_label is not None:
        custom_api = build_resteasy_url_with_train(train_url, train_label)
        if custom_api:
            api_url = custom_api
    logging.info("fetch_train_data called: train_url=%s train_label=%s api_url=%s", train_url, train_label, api_url)
    if api_url:
        response = requests.get(
            api_url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return response.text
    return fetch_train_page(train_url)


def build_status_text(info, train_label=None):
    status_icons = {
        "arrivato": "✅",
        "in transito": "🚄",
        "in coda": "⏳",
    }
    status_icon = status_icons.get(info.get("status", ""), "ℹ️")
    lines = [f"{status_icon} Treno {train_label or TRAIN_LABEL}"]

    if info.get("status"):
        lines.append(f"🔔 Stato: {info['status'].capitalize()}")

    if info.get("current_location") and info.get("current_time"):
        lines.append(f"📍 Ultimo rilevamento: {info['current_location']} alle {info['current_time']}")
    elif info.get("current_location"):
        lines.append(f"📍 Ultimo rilevamento: {info['current_location']}")

    if info.get("delay_minutes") is not None:
        lines.append(f"⏱ Ritardo: {info['delay_minutes']} min")

    if info.get("destination_arrival_actual"):
        lines.append(f"🛬 Arrivato a {info['destination']} alle {info['destination_arrival_actual']}")
    elif info.get("destination_arrival_predicted"):
        lines.append(f"🛬 Arrivo previsto a {info['destination']} alle {info['destination_arrival_predicted']}")
    else:
        lines.append(f"🛬 Destinazione: {info.get('destination', 'Sconosciuta')}")

    return "\n".join(lines)


def build_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Aggiorna ora", "callback_data": "CHECK_NOW"},
                {"text": "📡 Ultimo stato", "callback_data": "STATUS"},
            ],
            [{"text": "✏️ Imposta treno", "callback_data": "SET_TRAIN"}],
            [{"text": "ℹ️ Aiuto", "callback_data": "HELP"}],
        ]
    }


def build_welcome_text():
    return (
        f"👋 Ciao! Sono il bot di monitoraggio per il treno {TRAIN_LABEL}.\n"
        "Usa i pulsanti qui sotto per controllare lo stato attuale e aggiornare l’andamento.\n"
        "Puoi anche impostare un treno diverso con /settrain oppure con il pulsante dedicato."
    )


def build_help_text():
    return (
        "🛤️ Comandi disponibili:\n"
        "/settrain [numero] - Imposta il treno da seguire\n"
        "/check - Controlla lo stato del treno ora\n"
        "/status - Mostra l’ultimo stato salvato\n"
        "/help - Mostra questa guida\n\n"
        "Usa i pulsanti per aggiornare lo stato in modo facile e veloce."
    )


def build_message(info, prev_info, force=False, train_label=None):
    if force or not SEND_ONLY_ON_CHANGE:
        return build_status_text(info, train_label=train_label)
    if not prev_info:
        return build_status_text(info, train_label=train_label)
    if info != prev_info:
        return build_status_text(info, train_label=train_label)
    return None


def check_train_state(force=False, chat_id=None):
    if chat_id is None:
        state = load_state()
        prev_info = state.get("last_info", {})
        train_url = TRAIN_URL
        train_label = TRAIN_LABEL
    else:
        chat = get_chat_state(chat_id)
        prev_info = chat.get("last_info", {})
        chat_config = get_chat_config(chat_id)
        train_url = chat_config["train_url"]
        train_label = chat_config["train_label"]

    data = fetch_train_data(train_url=train_url, train_label=train_label)
    info = parse_train_info(data)
    message = build_message(info, {} if force else prev_info, force=force, train_label=train_label)

    if chat_id is None:
        state["last_info"] = info
    else:
        state = load_state()
        chats = state.setdefault("chats", {})
        chat = chats.setdefault(get_chat_key(chat_id), {})
        chat["last_info"] = info
        chats[get_chat_key(chat_id)] = chat

    save_state(state)
    return {
        "train_label": train_label,
        "train_url": train_url,
        "info": info,
        "send_only_on_change": SEND_ONLY_ON_CHANGE,
        "message": message,
        "sent": False,
    }


def run_check(force=False, chat_id=None):
    result = check_train_state(force=force, chat_id=chat_id)
    if result["message"] and chat_id is not None:
        send_telegram_message(result["message"], chat_id=chat_id)
        result["sent"] = True
    elif result["message"] and chat_id is None:
        send_telegram_message(result["message"])
        result["sent"] = True
    return result


def send_telegram_message(message, chat_id=None, reply_to_message_id=None, reply_markup=None):
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN or not chat_id:
        raise RuntimeError("Telegram credentials not configured.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)

    response = requests.post(url, data=payload, timeout=15)
    if response.status_code != 200:
        try:
            error_data = response.json()
            description = error_data.get("description")
        except Exception:
            description = response.text
        raise RuntimeError(
            f"Telegram API error {response.status_code}: {description}"
        )
    return True


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Telegram credentials not configured.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text is not None:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True

    response = requests.post(url, data=payload, timeout=15)
    if response.status_code != 200:
        try:
            error_data = response.json()
            description = error_data.get("description")
        except Exception:
            description = response.text
        raise RuntimeError(
            f"Telegram API error {response.status_code}: {description}"
        )
    return True


def register_bot_commands():
    """Register bot commands so Telegram shows them in the client UI."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    payload = {
        "commands": [
            {"command": "settrain", "description": "Imposta il treno da seguire"},
            {"command": "menu", "description": "Apri il menu dei pulsanti"},
            {"command": "check", "description": "Controlla lo stato del treno ora"},
            {"command": "status", "description": "Mostra l'ultimo stato salvato"},
            {"command": "help", "description": "Mostra la guida del bot"},
        ]
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        logging.info("setMyCommands: %s %s", resp.status_code, resp.text)
    except Exception as exc:
        logging.warning("Failed to register bot commands: %s", exc)


def handle_bot_command(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    chat_config = get_chat_config(chat_id)
    train_label = chat_config["train_label"]

    if text.startswith("/start"):
        send_telegram_message(build_welcome_text(), chat_id=chat_id)
        return

    if text.startswith("/help"):
        send_telegram_message(build_help_text(), chat_id=chat_id)
        return

    if text.startswith("/menu"):
        send_telegram_message("Seleziona un'azione dal menu:", chat_id=chat_id, reply_markup=build_menu_keyboard())
        return

    if text.startswith("/settrain"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            new_label = normalize_train_label(parts[1])
            if new_label:
                set_chat_config(chat_id, train_label=new_label, pending_action=None)
                send_telegram_message(
                    f"Treno impostato su {new_label}. Ora usa /check o /menu per aggiornare lo stato.",
                    chat_id=chat_id,
                )
                return
        set_chat_config(chat_id, pending_action="set_train")
        send_telegram_message("Inserisci il numero del treno da seguire.", chat_id=chat_id)
        return

    if text.startswith("/check"):
        result = check_train_state(force=True, chat_id=chat_id)
        send_telegram_message(build_status_text(result["info"], train_label=result["train_label"]), chat_id=chat_id)
        return

    if text.startswith("/status"):
        state = get_chat_state(chat_id)
        info = state.get("last_info")
        if not info:
            result = check_train_state(force=True, chat_id=chat_id)
            info = result["info"]
            train_label = result["train_label"]
        send_telegram_message(build_status_text(info, train_label=train_label), chat_id=chat_id)
        return

    pending_action = chat_config.get("pending_action")
    if pending_action == "set_train":
        new_label = normalize_train_label(text)
        if new_label:
            set_chat_config(chat_id, train_label=new_label, pending_action=None)
            send_telegram_message(f"Treno aggiornato a {new_label}. Ora puoi usare /check per vedere lo stato.", chat_id=chat_id)
            return
        send_telegram_message("Non ho trovato un numero treno valido. Invia solo il numero del treno.", chat_id=chat_id)
        return

    send_telegram_message("Non riconosco questo comando. Usa /help per vedere le opzioni.", chat_id=chat_id)


def handle_callback_query(callback_query):
    callback_id = callback_query["id"]
    data = callback_query["data"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]
    chat_config = get_chat_config(chat_id)
    train_label = chat_config["train_label"]

    if data == "CHECK_NOW":
        result = check_train_state(force=True, chat_id=chat_id)
        send_telegram_message(build_status_text(result["info"], train_label=result["train_label"]), chat_id=chat_id, reply_to_message_id=message_id)
        answer_callback_query(callback_id, text="Aggiornato!")
        return

    if data == "STATUS":
        state = get_chat_state(chat_id)
        info = state.get("last_info")
        if not info:
            result = check_train_state(force=True, chat_id=chat_id)
            info = result["info"]
            train_label = result["train_label"]
        send_telegram_message(build_status_text(info, train_label=train_label), chat_id=chat_id, reply_to_message_id=message_id)
        answer_callback_query(callback_id)
        return

    if data == "SET_TRAIN":
        set_chat_config(chat_id, pending_action="set_train")
        send_telegram_message("Invia ora il numero del treno da seguire.", chat_id=chat_id, reply_to_message_id=message_id)
        answer_callback_query(callback_id)
        return

    if data == "HELP":
        send_telegram_message(build_help_text(), chat_id=chat_id, reply_to_message_id=message_id)
        answer_callback_query(callback_id)
        return

    answer_callback_query(callback_id, text="Comando non riconosciuto.")


def process_telegram_update(update):
    if "message" in update:
        handle_bot_command(update["message"])
    elif "callback_query" in update:
        handle_callback_query(update["callback_query"])


@app.route("/")
def home():
    return "Train notifier web service is running. Use /check to trigger a status update."


@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(force=True)
    logging.info("Incoming telegram update: %s", json.dumps(update))
    try:
        process_telegram_update(update)
        return jsonify({"ok": True})
    except Exception as exc:
        logging.exception("Telegram webhook error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/check")
def check():
    force = request.args.get("force", "false").lower() in {"1", "true", "yes", "on"}
    try:
        result = run_check(force=force)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/status")
def status():
    state = load_state()
    return jsonify({"last_info": state.get("last_info", {}), "send_only_on_change": SEND_ONLY_ON_CHANGE})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
