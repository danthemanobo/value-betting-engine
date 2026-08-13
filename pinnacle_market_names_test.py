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

def parse_market_key(key):
    """Return a friendly market name from Pinnacle's key string."""
    # Example keys:
    # s;0;m -> Full Time 1X2
    # s;0;ou;2.5 -> Full Time Over/Under 2.5
    # s;0;s;0.5 -> Full Time Asian Handicap 0.5
    # s;0;tt;1.5;home -> Full Time Team Total Home 1.5
    # s;1;m -> Second Half 1X2, etc.

    parts = key.split(';')
    if len(parts) < 3:
        return key

    period = parts[1]  # 0 = full time, 1 = second half, etc.
    period_name = "Full Time" if period == "0" else f"Period {period}"
    market_code = parts[2]

    if market_code == 'm':
        return f"{period_name} 1X2"
    elif market_code == 'ou':
        line = parts[3] if len(parts) > 3 else ""
        return f"{period_name} Over/Under {line}"
    elif market_code == 's':
        line = parts[3] if len(parts) > 3 else ""
        return f"{period_name} Asian Handicap {line}"
    elif market_code == 'tt':
        line = parts[3] if len(parts) > 3 else ""
        side = parts[4] if len(parts) > 4 else ""
        side_name = "Home" if side == 'home' else "Away" if side == 'away' else side
        return f"{period_name} Team Total {side_name} {line}"
    else:
        return key

def label_prices_for_market(market, home_name, away_name):
    """Return a list of (selection_name, decimal_odds) for each price."""
    labels = []
    prices = market.get("prices", [])
    key = market.get("key", "")
    market_type = market.get("type", "")

    # Determine order of selections based on market type and key
    if market_type == "moneyline":
        # Always home, draw, away (if 3 prices)
        if len(prices) == 3:
            return [(home_name, american_to_decimal(prices[0]["price"])),
                    ("Draw", american_to_decimal(prices[1]["price"])),
                    (away_name, american_to_decimal(prices[2]["price"]))]
        else:
            return [(home_name, american_to_decimal(prices[0]["price"])),
                    (away_name, american_to_decimal(prices[1]["price"]))] if len(prices) == 2 else []

    elif market_type in ("total", "team_total"):
        # First price Over, second Under (typical)
        if len(prices) == 2:
            return [("Over", american_to_decimal(prices[0]["price"])),
                    ("Under", american_to_decimal(prices[1]["price"]))]
        else:
            return []

    elif market_type == "spread":
        # Asian handicap: prices have points (e.g., 0.5 and -0.5). First is home, second away.
        if len(prices) == 2:
            home_point = prices[0].get("points", "")
            away_point = prices[1].get("points", "")
            return [(f"{home_name} {home_point}", american_to_decimal(prices[0]["price"])),
                    (f"{away_name} {away_point}", american_to_decimal(prices[1]["price"]))]
        else:
            return []

    else:
        return []

def main():
    headers = {
        "x-api-key": API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    league_id = 1980  # Premier League
    matchups_url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups"
    try:
        resp = requests.get(matchups_url, headers=headers, timeout=20)
        resp.raise_for_status()
        matchups = resp.json()
    except Exception as e:
        send_telegram_plain(f"Error fetching matchups: {e}")
        return

    # Find first regular match
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
    if not home_name or not away_name:
        send_telegram_plain("Could not determine team names.")
        return

    start_time = target_match.get("startTime", "Unknown")

    markets_url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/straight"
    try:
        resp = requests.get(markets_url, headers=headers, timeout=20)
        resp.raise_for_status()
        all_markets = resp.json()
    except Exception as e:
        send_telegram_plain(f"Error fetching markets: {e}")
        return

    match_markets = [m for m in all_markets if m.get("matchupId") == matchup_id]

    if not match_markets:
        send_telegram_plain(f"No markets found for {home_name} vs {away_name}")
        return

    lines = []
    lines.append(f"⚽ {home_name} vs {away_name}")
    lines.append(f"Start: {start_time}")
    lines.append("")

    for market in match_markets:
        key = market.get("key", "")
        market_name = parse_market_key(key)
        labels = label_prices_for_market(market, home_name, away_name)

        if labels:
            line = f"📌 {market_name}\n"
            for sel, odds in labels:
                line += f"   {sel}: {odds}\n"
            lines.append(line.strip())
        else:
            # Fallback: just show raw key and prices with points
            price_str = ", ".join([f"{p.get('points','')}: {american_to_decimal(p['price'])}" for p in market.get("prices", [])])
            lines.append(f"❓ {market_name} (raw)\n   {price_str}")

    full_msg = "\n\n".join(lines)
    send_telegram_plain(full_msg[:12000])

if __name__ == "__main__":
    main()
