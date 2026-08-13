import os, json, re, requests, unicodedata
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def main():
    # ========== DIAGNOSTIC BLOCK ==========
    debug_lines = []
    try:
        docs = db.collection("matches").limit(5).stream()
        doc_list = list(docs)
        debug_lines.append(f"Total docs fetched: {len(doc_list)}")
        for d in doc_list:
            data = d.to_dict()
            debug_lines.append(f"Doc ID: {d.id}")
            debug_lines.append(f"Keys: {list(data.keys())}")
            if "markets" in data:
                debug_lines.append(f"Markets count: {len(data['markets'])}")
            else:
                debug_lines.append("No 'markets' field")
    except Exception as e:
        debug_lines.append(f"Firestore read error: {e}")

    send_telegram("🔍 Firestore Diagnostic:\n" + "\n".join(debug_lines))
    return  # Stop here for diagnosis; we'll resume full logic once we see this.

if __name__ == "__main__":
    main()
