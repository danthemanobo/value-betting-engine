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

# ── De‑vig (just copy functions, they won't be fully used now) ──
def de_vig_two_way(o1, o2):
    imp1 = 1/o1; imp2 = 1/o2; ov = imp1+imp2
    return imp1/ov, imp2/ov

def de_vig_three_way(o1, o2, o3):
    imp1 = 1/o1; imp2 = 1/o2; imp3 = 1/o3; ov = imp1+imp2+imp3
    return imp1/ov, imp2/ov, imp3/ov

# ── Telegram ──
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        resp.raise_for_status()
        print("Telegram OK")
    except Exception as e:
        print(f"Telegram error: {e}")

# ── Main (no time check) ──
def main():
    now_utc = datetime.now(timezone.utc)
    print(f"Scanning at {now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")} (manual test)")

    # 1. Fetch matches from API for next 90 minutes
    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals,btts,double_chance",
        "oddsFormat": "decimal",
        "commenceTimeFrom": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commenceTimeTo": (now_utc + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    # 2. (Simplified) Just log to Firestore and send a test message
    for match in matches[:5]:  # only log first 5 to keep it quick
        match_id = match['id']
        home = match['home_team']
        away = match['away_team']
        kickoff = match['commence_time']
        # Write a minimal doc to Firestore
        db.collection('matches').document(match_id).set({
            'home': home,
            'away': away,
            'kickoff': kickoff
        }, merge=True)

    send_telegram(f"✅ Test scan done. {len(matches)} matches found. First: {matches[0]['home_team']} vs {matches[0]['away_team']}")
    print("Done")

if __name__ == '__main__':
    main()
