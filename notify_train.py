import json
import os
import re
import requests
from flask import Flask, jsonify, request
from bs4 import BeautifulSoup

DEFAULT_TRAIN_URL = "http://www.viaggiatreno.it/infomobilitamobile/pages/cercaTreno/cercaTreno.jsp?treno=8807&origine=S01700&datapartenza=1784930400000"
TRAIN_URL = os.getenv("TRAIN_URL", DEFAULT_TRAIN_URL)
TRAIN_LABEL = os.getenv("TRAIN_LABEL", "8807")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE_PATH = os.getenv("STATE_FILE_PATH", "train_state.json")
SEND_ONLY_ON_CHANGE = os.getenv("SEND_ONLY_ON_CHANGE", "true").lower() in {"1", "true", "yes", "on"}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def fetch_train_page():
    response = requests.get(
        TRAIN_URL,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.text


def parse_train_info(html):
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


def build_message(info, prev_info):
    if info["destination_arrival_actual"]:
        if prev_info.get("destination_arrival_actual") != info["destination_arrival_actual"]:
            delay = f" con ritardo {info['delay_minutes']} min" if info["delay_minutes"] is not None else ""
            return f"Treno {TRAIN_LABEL} è arrivato a Taranto alle {info['destination_arrival_actual']}{delay}."

    if info["destination_arrival_predicted"]:
        if (
            prev_info.get("destination_arrival_predicted") != info["destination_arrival_predicted"]
            or prev_info.get("delay_minutes") != info["delay_minutes"]
        ):
            delay = f" con ritardo {info['delay_minutes']} min" if info["delay_minutes"] is not None else ""
            return f"Treno {TRAIN_LABEL}: arrivo previsto a Taranto {info['destination_arrival_predicted']}{delay}."

    if (
        prev_info.get("current_location") != info["current_location"]
        or prev_info.get("current_time") != info["current_time"]
        or prev_info.get("status") != info["status"]
    ):
        parts = []
        if info["status"]:
            parts.append(info["status"].capitalize())
        if info["current_location"] and info["current_time"]:
            parts.append(f"ultimo rilevamento a {info['current_location']} alle {info['current_time']}")
        if info["destination_arrival_predicted"]:
            parts.append(f"arrivo previsto {info['destination_arrival_predicted']}")
        if info["delay_minutes"] is not None:
            parts.append(f"ritardo {info['delay_minutes']} min")
        return f"Treno {TRAIN_LABEL}: {'; '.join(parts)}."

    return None


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    response = requests.post(url, data=payload, timeout=15)
    response.raise_for_status()
    return True


def run_check(force=False):
    state = load_state()
    prev_info = state.get("last_info", {})

    html = fetch_train_page()
    info = parse_train_info(html)
    message = None

    if force:
        message = build_message(info, {})
    else:
        message = build_message(info, prev_info) if SEND_ONLY_ON_CHANGE else build_message(info, {})

    result = {
        "train_label": TRAIN_LABEL,
        "train_url": TRAIN_URL,
        "info": info,
        "send_only_on_change": SEND_ONLY_ON_CHANGE,
        "message": None,
        "sent": False,
    }

    if message:
        try:
            send_telegram_message(message)
            result["message"] = message
            result["sent"] = True
        except Exception as exc:
            result["message"] = f"ERROR: {exc}"
    else:
        result["message"] = "No state change detected; no message sent."

    state["last_info"] = info
    save_state(state)
    return result


@app.route("/")
def home():
    return "Train notifier web service is running. Use /check to trigger a status update."


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
