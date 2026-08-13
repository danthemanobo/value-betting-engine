import os, json, requests

API_KEY = os.environ['PINNACLE_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram_plain(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def main():
    league_id = 1980  # England Premier League
    endpoints = [
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/straight",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups?page=1",
    ]

    headers = {
        "x-api-key": API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    results = []
    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            status = resp.status_code
            snippet = resp.text[:800]
            results.append(f"URL: {url}\nStatus: {status}\nSnippet: {snippet}\n---")
        except Exception as e:
            results.append(f"URL: {url}\nError: {e}\n---")

    full_msg = "🔍 Pinnacle Matchup Probe:\n\n" + "\n".join(results)
    send_telegram_plain(full_msg[:12000])

if __name__ == "__main__":
    main()
