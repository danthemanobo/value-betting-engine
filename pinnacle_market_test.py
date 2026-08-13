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

def american_to_decimal(american):
    if american > 0:
        return round(1 + american/100, 3)
    else:
        return round(1 + 100/abs(american), 3)

def main():
    headers = {
        "x-api-key": API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # 1. Get Premier League matchups
    league_id = 1980
    matchups_url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups"
    try:
        resp = requests.get(matchups_url, headers=headers, timeout=20)
        resp.raise_for_status()
        matchups = resp.json()
    except Exception as e:
        send_telegram_plain(f"Error fetching matchups: {e}")
        return

    # Find first real match (type='matchup')
    target_match = None
    for m in matchups:
        if m.get("type") == "matchup":
            target_match = m
            break
    if not target_match:
        send_telegram_plain("No regular match found in Premier League.")
        return

    matchup_id = target_match["id"]
    home_name = None
    away_name = None
    participant_map = {}  # id -> name and alignment

    for p in target_match["participants"]:
        participant_map[p["id"]] = {
            "name": p["name"],
            "alignment": p.get("alignment")
        }
        if p.get("alignment") == "home":
            home_name = p["name"]
        elif p.get("alignment") == "away":
            away_name = p["name"]

    start_time = target_match.get("startTime", "Unknown")
    print(f"Selected match: {home_name} vs {away_name} (ID {matchup_id})")

    # 2. Get straight markets for the league
    markets_url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/straight"
    try:
        resp = requests.get(markets_url, headers=headers, timeout=20)
        resp.raise_for_status()
        all_markets = resp.json()
    except Exception as e:
        send_telegram_plain(f"Error fetching markets: {e}")
        return

    # Filter markets for our selected match
    match_markets = [m for m in all_markets if m.get("matchupId") == matchup_id]

    if not match_markets:
        send_telegram_plain(f"No markets found for match {home_name} vs {away_name}")
        return

    # Build report
    lines = []
    lines.append(f"⚽ {home_name} vs {away_name}")
    lines.append(f"Start: {start_time}")
    lines.append("")
    for market in match_markets:
        market_type = market.get("type", "unknown")
        period = market.get("period", 0)
        prices = market.get("prices", [])
        points = ""
        price_parts = []
        for p in prices:
            price_american = p.get("price")
            points = p.get("points")
            participant_id = p.get("participantId")
            participant_name = participant_map.get(participant_id, {}).get("name", f"ID {participant_id}")
            decimal = american_to_decimal(price_american)
            if points is not None and points != 0:
                price_parts.append(f"{participant_name} ({points}): {decimal}")
            else:
                price_parts.append(f"{participant_name}: {decimal}")
        line = f"Type: {market_type} (Period {period})"
        if market.get("key"):
            line += f" Key: {market['key']}"
        line += "\n  " + "\n  ".join(price_parts)
        lines.append(line)

    full_msg = "\n".join(lines)
    send_telegram_plain(full_msg[:12000])  # split automatically if >4000

if __name__ == "__main__":
    main()
