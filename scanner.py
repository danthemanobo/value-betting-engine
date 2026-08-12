import os, json, requests
from firebase_admin import credentials, firestore, initialize_app

API_KEY = os.environ['ODDS_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])

cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        print("Telegram OK")
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    print("Fetching EPL h2h and totals...")
    params = {
        "apiKey": API_KEY,
        "regions": "eu",                # Pinnacle
        "markets": "h2h,totals",        # only free markets
        "oddsFormat": "decimal"
    }
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports/soccer_epl/odds", params=params, timeout=30)
        resp.raise_for_status()
        matches = resp.json()
    except Exception as e:
        send_telegram(f"❌ API error: {e}")
        print(f"API error: {e}")
        return

    if not matches:
        send_telegram("ℹ️ No EPL matches found.")
        return

    # Store first match and send test alert
    first = matches[0]
    db.collection('matches').document(first['id']).set({
        'home': first['home_team'],
        'away': first['away_team'],
        'kickoff': first['commence_time']
    }, merge=True)

    send_telegram(f"✅ Test OK. {len(matches)} EPL matches. First: {first['home_team']} vs {first['away_team']}")

if __name__ == '__main__':
    main()
