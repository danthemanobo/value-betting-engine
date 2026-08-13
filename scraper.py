import os, json, re, requests, unicodedata
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

MIN_EV = 0.05

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def normalize(name):
    return re.sub(r'\s+', ' ', strip_accents(name).replace('-', ' ')).strip().lower()

def parse_betpawa_page(body_text):
    """
    Extract markets from Betpawa match page body.
    Returns list of market dicts:
    {
        "header": original header line,
        "type": "1x2" | "double_chance" | "btts" | "total" | "team_total" | "next_goal" | "handicap",
        "selections": [(label, odds), ...]
    }
    """
    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
    markets = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Identify market headers
        if '|' not in line:
            i += 1
            continue

        header = line
        i += 1
        selections = []

        # Collect until next header (line with '|')
        while i < len(lines) and '|' not in lines[i]:
            label = lines[i]
            if i+1 < len(lines):
                try:
                    odds = float(lines[i+1])
                    selections.append((label, odds))
                    i += 2
                except ValueError:
                    i += 1
            else:
                i += 1

        if selections:
            # Determine market type from header
            header_lower = header.lower()
            if '1x2 1up' in header_lower or '1x2 2up' in header_lower:
                # skip these for now (alternate 1X2)
                pass
            elif '1x2' in header_lower:
                markets.append({"header": header, "type": "1x2", "selections": selections})
            elif 'double chance' in header_lower:
                markets.append({"header": header, "type": "double_chance", "selections": selections})
            elif 'both teams to score' in header_lower:
                markets.append({"header": header, "type": "btts", "selections": selections})
            elif 'next goal' in header_lower:
                markets.append({"header": header, "type": "next_goal", "selections": selections})
            elif 'over/under' in header_lower and 'full time' in header_lower:
                # Could be total market or team total
                if '|' in header:
                    parts = header.split('|')
                    # e.g., "Over/Under | Full Time" or "Over/Under | Arsenal FC | Full Time"
                    if len(parts) >= 3:
                        team_name = parts[1].strip()
                        markets.append({"header": header, "type": "team_total", "team": team_name, "selections": selections})
                    else:
                        markets.append({"header": header, "type": "total", "selections": selections})
                else:
                    markets.append({"header": header, "type": "total", "selections": selections})
            elif 'handicap' in header_lower:
                markets.append({"header": header, "type": "handicap", "selections": selections})
            else:
                markets.append({"header": header, "type": "unknown", "selections": selections})
        # else skip if no selections found

    return markets

def split_total_markets(market):
    """
    For total/team_total markets, Betpawa returns a list of alternating Over/Under lines.
    This function splits them into individual markets with line and type.
    Returns list of dicts: { "line": 2.5, "type": "total", "selections": [(Over, odds), (Under, odds)] }
    """
    results = []
    selections = market["selections"]
    i = 0
    while i < len(selections):
        label1, odds1 = selections[i]
        if label1.lower().startswith('over'):
            # Expect next label to be 'Under'
            if i+1 < len(selections) and selections[i+1][0].lower().startswith('under'):
                label2, odds2 = selections[i+1]
                # Extract line from label like "Over 2.5"
                try:
                    line = float(label1.split()[-1])
                except:
                    line = None
                results.append({
                    "line": line,
                    "type": market.get("type", "total"),
                    "team": market.get("team"),
                    "selections": [("Over", odds1), ("Under", odds2)]
                })
                i += 2
            else:
                i += 1
        else:
            i += 1
    return results

def match_betpawa_to_pinnacle(bet_market, pinnacle_markets):
    """
    Match a parsed Betpawa market to the corresponding Pinnacle market.
    Returns (pinnacle_market, score) or (None, 0)
    """
    bet_type = bet_market["type"]
    best = None
    best_score = 0
    for pm in pinnacle_markets:
        pm_name = pm.get("market_name", "")
        # Fuzzy match on market name
        score = fuzz.partial_ratio(normalize(bet_market["header"]), normalize(pm_name))
        # Also use type-specific hints
        if bet_type == "1x2" and pm.get("type") == "moneyline":
            score += 10
        elif bet_type == "total" and pm.get("type") == "total":
            # If line is available, check if line appears in name
            if bet_market.get("line") and str(bet_market["line"]) in pm_name:
                score += 30
        elif bet_type == "team_total" and pm.get("type") == "team_total":
            if bet_market.get("line") and str(bet_market["line"]) in pm_name:
                score += 30
            if bet_market.get("team"):
                team_norm = normalize(bet_market["team"])
                if team_norm in normalize(pm_name):
                    score += 20
        if score > best_score and score > 60:
            best_score = score
            best = pm
    return best, best_score

def main():
    now_utc = datetime.now(timezone.utc)
    # Fetch stored matches with markets
    all_docs = db.collection("matches").stream()
    matches_list = []
    for doc in all_docs:
        data = doc.to_dict()
        if "markets" in data and isinstance(data["markets"], list) and len(data["markets"]) > 0:
            data["doc_id"] = doc.id
            matches_list.append(data)

    matches_list = matches_list[:3]

    if not matches_list:
        send_telegram("ℹ️ No stored Pinnacle matches with markets found.")
        return

    report_lines = []
    report_lines.append(f"📊 Processing {len(matches_list)} matches.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for match in matches_list:
            home_raw = match.get("home", "")
            away_raw = match.get("away", "")
            home_norm = normalize(home_raw)
            away_norm = normalize(away_raw)
            pinnacle_markets = match.get("markets", [])

            report_lines.append(f"\n⚽ {home_raw} vs {away_raw}")

            try:
                # Navigate to events page
                page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(3000)

                # Search for home team
                search_icon = page.query_selector("button[aria-label*='search' i]")
                if search_icon:
                    search_icon.click()
                    page.wait_for_timeout(1000)
                search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
                if not search_input:
                    report_lines.append("❌ Search input missing")
                    continue

                search_input.fill(home_raw)
                search_input.press("Enter")
                page.wait_for_timeout(5000)

                correct_found = False
                attempts = 0
                max_attempts = 20

                while not correct_found and attempts < max_attempts:
                    attempts += 1
                    result_elements = page.query_selector_all("div[class*='event']")
                    for idx in range(len(result_elements)):
                        # Re-search fresh before each click
                        if idx > 0:
                            # Go back to search results
                            page.go_back()
                            page.wait_for_timeout(2000)
                            search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
                            if search_input:
                                search_input.fill(home_raw)
                                search_input.press("Enter")
                                page.wait_for_timeout(5000)
                                result_elements = page.query_selector_all("div[class*='event']")
                        if idx >= len(result_elements):
                            break

                        elem = result_elements[idx]
                        text = elem.inner_text()
                        text_lower = strip_accents(text).lower()
                        if 'football' not in text_lower:
                            continue

                        try:
                            elem.click()
                            page.wait_for_timeout(5000)
                        except:
                            continue

                        body_text = page.inner_text("body")
                        body_lower = strip_accents(body_text).lower()
                        if home_norm in body_lower and away_norm in body_lower:
                            correct_found = True
                            break
                        else:
                            # Wrong match, go back
                            page.go_back()
                            page.wait_for_timeout(2000)

                if not correct_found:
                    report_lines.append("❌ Correct match not found on Betpawa")
                    continue

                # Parse markets from body text
                bet_markets = parse_betpawa_page(body_text)

                for bet_market in bet_markets:
                    # Split total/team_total markets into individual lines
                    if bet_market["type"] in ("total", "team_total"):
                        sub_markets = split_total_markets(bet_market)
                    else:
                        sub_markets = [bet_market]

                    for sub in sub_markets:
                        pinnacle_market, score = match_betpawa_to_pinnacle(sub, pinnacle_markets)
                        if not pinnacle_market:
                            continue

                        true_probs = [s["true_prob"] for s in pinnacle_market["selections"]]
                        # Align selections: if counts match, zip in order; else try fuzzy label matching
                        if len(sub["selections"]) == len(true_probs):
                            paired = list(zip(sub["selections"], true_probs))
                        else:
                            paired = []
                            for label, odds in sub["selections"]:
                                # find best matching selection name
                                best_tp = None
                                best_sel_score = 0
                                for sel in pinnacle_market["selections"]:
                                    sel_score = fuzz.partial_ratio(normalize(label), normalize(sel["name"]))
                                    if sel_score > best_sel_score:
                                        best_sel_score = sel_score
                                        best_tp = sel["true_prob"]
                                if best_tp is not None and best_sel_score > 50:
                                    paired.append(((label, odds), best_tp))

                        if not paired:
                            continue

                        evs = []
                        for (label, bet_odd), true_prob in paired:
                            ev = (true_prob * bet_odd) - 1
                            evs.append((label, bet_odd, true_prob, ev))

                        report_lines.append(f"📌 {sub['header']} (match {score})")
                        for label, bet_odd, tp, ev in evs:
                            flag = "🚀" if ev > MIN_EV else ""
                            report_lines.append(f"   {label}: Betpawa {bet_odd} | TP {tp:.2f} | EV {ev*100:+.1f}% {flag}")

            except Exception as e:
                report_lines.append(f"⚠️ Exception: {e}")

        browser.close()

    full_report = "\n".join(report_lines)
    send_telegram(full_report)

if __name__ == "__main__":
    main()
