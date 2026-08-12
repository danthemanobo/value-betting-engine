import os, requests
from datetime import datetime, timezone

API_KEY = os.environ['ODDS_API_KEY']
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    params = {
        "apiKey": API_KEY,
        "regions": "eu",          # Pinnacle
        "markets": "h2h",         # 1X2 only for test
        "oddsFormat": "decimal"
    }
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports/soccer/odds", params=params, timeout=30)
        resp.raise_for_status()
        matches = resp.json()
        print(f"Total matches: {len(matches)}")
        # Send first 3 matches with kickoff times to Telegram
        sample = "\n".join([
            f"{m['home_team']} vs {m['away_team']} @ {m['commence_time']}"
            for m in matches[:3]
        ])
        send_telegram(f"API test: {len(matches)} matches. Sample:\n{sample}")
    except Exception as e:
        send_telegram(f"API test error: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
