import os, json, requests
from datetime import datetime, timedelta, timezone
from firebase_admin import credentials, firestore, initialize_app

API_KEY = os.environ['ODDS_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])

cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

def get_real_utc_now():
    """Try to get real UTC time from an external API, fallback to system time."""
    try:
        resp = requests.get("http://worldtimeapi.org/api/timezone/Etc/UTC", timeout=5)
        if resp.status_code == 200:
            dt_str = resp.json()["datetime"]  # e.g., "2025-08-12T14:20:00.000000+00:00"
            return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"Real-time API failed: {e}, falling back to system clock.")
    return datetime.now(timezone.utc)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        print("Telegram OK")
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    now_utc = get_real_utc_now()
    window_start = now_utc
    window_end = now_utc + timedelta(minutes=90)
    print(f"Real UTC now: {now_utc.isoformat()}")
    print(f"Scanning matches between {window_start.strftime('%Y-%m-%d %H:%M')} and {window_end.strftime('%Y-%m-%d %H:%M')} UTC")

    # Fetch all soccer matches with free markets
    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports/soccer/odds", params=params, timeout=30)
        resp.raise_for_status()
        all_matches = resp.json()
    except Exception as e:
        send_telegram(f"❌ API error: {e}")
        print(f"API error: {e}")
        return

    print(f"Total matches fetched: {len(all_matches)}")

    # Filter matches within our window
    filtered = []
    for match in all_matches:
        try:
            kickoff = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
        except:
            continue  # skip malformed dates
        if window_start <= kickoff < window_end:
            filtered.append(match)

    print(f"Matches in window: {len(filtered)}")

    if not filtered:
        send_telegram("ℹ️ No matches starting in the next 90 minutes.")
        return

    # Store first 10 matches in Firestore (for testing; later we'll store all)
    for match in filtered[:10]:
        db.collection('matches').document(match['id']).set({
            'home': match['home_team'],
            'away': match['away_team'],
            'kickoff': match['commence_time'],
            'stored_at': now_utc.isoformat()
        }, merge=True)

    # Build alert message
    first = filtered[0]
    msg = f"⚽ {len(filtered)} matches in next 90 min\nFirst: {first['home_team']} vs {first['away_team']} at {first['commence_time']}"
    send_telegram(msg)
    print("Done")

if __name__ == '__main__':
    main()
