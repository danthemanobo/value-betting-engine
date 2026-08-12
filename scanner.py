import os, json, requests
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

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        resp.raise_for_status()
        print("Telegram OK")
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    print("Fetching all upcoming soccer matches...")

    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals,both_teams_to_score,double_chance",  # 'btts' corrected to official key
        "oddsFormat": "decimal"
    }
    try:
        resp = requests.get(f"{BASE_URL}/soccer_epl/odds", params=params, timeout=30)  # change to soccer_epl for EPL only? Or keep broad: /upcoming is not a valid sport key; we need a sport key like 'soccer_epl' or 'soccer'. We'll use 'soccer' for all leagues.
        resp.raise_for_status()
        matches = resp.json()
    except Exception as e:
        send_telegram(f"❌ API error: {e}")
        print(f"API error: {e}")
        return

    print(f"Fetched {len(matches)} matches")

    if not matches:
        send_telegram("ℹ️ No upcoming matches found.")
        return

    # Log first match to Firestore as test
    first = matches[0]
    db.collection('matches').document(first['id']).set({
        'home': first['home_team'],
        'away': first['away_team'],
        'kickoff': first['commence_time']
    }, merge=True)

    send_telegram(f"✅ Test scan done. {len(matches)} matches found. First: {first['home_team']} vs {first['away_team']}")
    print("Done")

if __name__ == '__main__':
    main()
