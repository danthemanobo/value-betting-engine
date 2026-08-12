import os, json, requests
from datetime import datetime, timezone, timedelta
from firebase_admin import credentials, firestore, initialize_app

# ── Init ──
API_KEY = os.environ['ODDS_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])

cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BASE_URL = "https://api.the-odds-api.com/v4/sports"

# ── Telegram ──
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        resp.raise_for_status()
        print("Telegram OK")
    except Exception as e:
        print(f"Telegram error: {e}")

# ── Main ──
def main():
    now_utc = datetime.now(timezone.utc)
    time_from = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_to = (now_utc + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Scanning at {time_from} (manual test)")

    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals,btts,double_chance",
        "oddsFormat": "decimal",
        "commenceTimeFrom": time_from,
        "commenceTimeTo": time_to
    }
    try:
        resp = requests.get(f"{BASE_URL}/upcoming/odds", params=params, timeout=30)
        resp.raise_for_status()
        matches = resp.json()
    except Exception as e:
        send_telegram(f"❌ API error: {e}")
        print(f"API error: {e}")
        return

    print(f"Fetched {len(matches)} matches")

    if not matches:
        send_telegram("ℹ️ No matches in the next 90 minutes.")
        return

    for match in matches[:5]:
        match_id = match['id']
        db.collection('matches').document(match_id).set({
            'home': match['home_team'],
            'away': match['away_team'],
            'kickoff': match['commence_time']
        }, merge=True)

    send_telegram(f"✅ Test scan done. {len(matches)} matches found. First: {matches[0]['home_team']} vs {matches[0]['away_team']}")
    print("Done")

if __name__ == '__main__':
    main()
