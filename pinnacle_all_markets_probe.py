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
    headers = {
        "x-api-key": API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    league_id = 1980  # Premier League

    # 1. Fetch first regular match
    matchups_url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups"
    try:
        resp = requests.get(matchups_url, headers=headers, timeout=20)
        resp.raise_for_status()
        matchups = resp.json()
    except Exception as e:
        send_telegram_plain(f"Error fetching matchups: {e}")
        return

    target_match = None
    for m in matchups:
        if m.get("type") == "matchup":
            target_match = m
            break
    if not target_match:
        send_telegram_plain("No regular match found.")
        return

    matchup_id = target_match["id"]
    home_name = None
    away_name = None
    for p in target_match.get("participants", []):
        if p.get("alignment") == "home":
            home_name = p.get("name")
        elif p.get("alignment") == "away":
            away_name = p.get("name")

    print(f"Probing markets for {home_name} vs {away_name} (ID {matchup_id})")

    # Candidate endpoint patterns based on typical Pinnacle Arcadia API.
    # Some may require query params or different structure.
    candidate_urls = [
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/straight",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/related",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/alternate",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/specials",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/player",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/team",
        f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/main",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/straight",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/related",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/alternate",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/specials",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/player",
        f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/team",
    ]

    results = []
    for url in candidate_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            status = resp.status_code
            snippet = resp.text[:300]
            results.append(f"URL: {url}\nStatus: {status}\nSnippet: {snippet}\n---")
        except Exception as e:
            results.append(f"URL: {url}\nError: {e}\n---")

    full_msg = "🔍 Pinnacle All Markets Probe:\n\n" + "\n".join(results)
    send_telegram_plain(full_msg[:12000])

if __name__ == "__main__":
    main()
