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

# ---------- Pinnacle Key Parsing ----------
def parse_pinnacle_key(key):
    """Extract structured info from Pinnacle key like 's;0;ou;2.5'."""
    parts = key.split(';')
    if len(parts) < 3:
        return None
    period = parts[1]  # 0=full, 1=first half, 2=second half
    code = parts[2]
    info = {
        "period": period,
        "type": None,
        "line": None,
        "side": None
    }
    if code == 'm':
        info["type"] = "1x2"
    elif code == 'ou':
        info["type"] = "total"
        if len(parts) > 3:
            info["line"] = parts[3]
    elif code == 's':
        info["type"] = "spread"
        if len(parts) > 3:
            info["line"] = parts[3]
    elif code == 'tt':
        info["type"] = "team_total"
        if len(parts) > 3:
            info["line"] = parts[3]
        if len(parts) > 4:
            info["side"] = parts[4]  # 'home' or 'away'
    else:
        return None
    return info

def canonical_key_from_pinnacle(info):
    """Build a canonical key string for strict matching."""
    period = info.get("period", "0")
    type_ = info.get("type")
    line = info.get("line")
    side = info.get("side")
    if type_ == "1x2":
        return f"1x2_{period}"
    elif type_ == "total":
        return f"total_{period}_{line}"
    elif type_ == "team_total":
        return f"team_total_{period}_{side}_{line}"
    elif type_ == "spread":
        return f"spread_{period}_{line}"
    return None

# ---------- Betpawa Market Parsing ----------
def parse_betpawa_page(body_text):
    """
    Extract markets from Betpawa page.
    Returns list of market dicts: {header, type, period, line, team, selections}
    """
    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
    markets = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '|' not in line:
            i += 1
            continue
        header = line
        i += 1
        selections = []
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

        if not selections:
            continue

        header_lower = header.lower()

        # Determine period
        period = "0"  # full time default
        if 'first half' in header_lower:
            period = "1"
        elif 'second half' in header_lower:
            period = "2"

        # Market type
        if '1x2' in header_lower and '1up' not in header_lower and '2up' not in header_lower:
            markets.append({
                "header": header,
                "type": "1x2",
                "period": period,
                "line": None,
                "team": None,
                "selections": selections
            })
        elif 'over/under' in header_lower:
            # Could be total or team total
            if '|' in header:
                parts = header.split('|')
                # e.g., "Over/Under | Full Time" or "Over/Under | Arsenal FC | Full Time"
                if len(parts) >= 3 and 'full time' in parts[2].lower():
                    team = parts[1].strip()
                    # Team total
                    for sel in selections:
                        label, odds = sel
                        if label.lower().startswith('over'):
                            line_str = label.split()[-1]
                            try:
                                line = float(line_str)
                            except:
                                line = None
                            markets.append({
                                "header": f"{header} {line}",
                                "type": "team_total",
                                "period": period,
                                "line": line,
                                "team": team,
                                "selections": [("Over", odds)]
                            })
                            # find Under
                            idx = selections.index(sel)
                            if idx+1 < len(selections):
                                under_sel = selections[idx+1]
                                if under_sel[0].lower().startswith('under'):
                                    markets[-1]["selections"].append(("Under", under_sel[1]))
                else:
                    # Total market: lines separated
                    for sel in selections:
                        label, odds = sel
                        if label.lower().startswith('over'):
                            line_str = label.split()[-1]
                            try:
                                line = float(line_str)
                            except:
                                line = None
                            markets.append({
                                "header": f"{header} {line}",
                                "type": "total",
                                "period": period,
                                "line": line,
                                "team": None,
                                "selections": [("Over", odds)]
                            })
                            idx = selections.index(sel)
                            if idx+1 < len(selections):
                                under_sel = selections[idx+1]
                                if under_sel[0].lower().startswith('under'):
                                    markets[-1]["selections"].append(("Under", under_sel[1]))
        # Ignore other markets for now

    return markets

def canonical_key_from_betpawa(market):
    """Build canonical key for Betpawa market."""
    type_ = market["type"]
    period = market.get("period", "0")
    line = market.get("line")
    team = market.get("team")
    if type_ == "1x2":
        return f"1x2_{period}"
    elif type_ == "total":
        return f"total_{period}_{line}"
    elif type_ == "team_total":
        side = "home" if team and 'home' in team.lower() else "away"
        return f"team_total_{period}_{side}_{line}"
    return None

def main():
    now_utc = datetime.now(timezone.utc)
    # Fetch matches with markets, filter out specials
    all_docs = db.collection("matches").stream()
    matches_list = []
    for doc in all_docs:
        data = doc.to_dict()
        if "markets" not in data or not isinstance(data.get("markets"), list) or len(data["markets"]) == 0:
            continue
        home = data.get("home", "")
        away = data.get("away", "")
        if "(Corners)" in home or "(Corners)" in away or "(Bookings)" in home or "(Bookings)" in away:
            continue
        data["doc_id"] = doc.id
        matches_list.append(data)

    matches_list = matches_list[:3]  # limit for testing

    if not matches_list:
        send_telegram("ℹ️ No suitable regular matches with markets found.")
        return

    report_lines = [f"📊 Processing {len(matches_list)} matches."]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for match in matches_list:
            home_raw = match.get("home", "")
            away_raw = match.get("away", "")
            home_norm = normalize(home_raw)
            away_norm = normalize(away_raw)

            # Build Pinnacle market index by canonical key
            pinnacle_index = {}
            for pm in match.get("markets", []):
                key = pm.get("key")
                info = parse_pinnacle_key(key)
                if info:
                    ck = canonical_key_from_pinnacle(info)
                    if ck:
                        pinnacle_index[ck] = pm  # assume unique per match

            report_lines.append(f"\n⚽ {home_raw} vs {away_raw}")

            try:
                page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(3000)

                # Click search icon and search for home team
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
                        elem = page.locator("div[class*='event']").nth(idx)
                        try:
                            text = elem.inner_text(timeout=2000)
                        except Exception:
                            continue
                        text_lower = strip_accents(text).lower()
                        if 'football' not in text_lower:
                            continue
                        try:
                            elem.click()
                            page.wait_for_timeout(5000)
                        except Exception:
                            continue

                        try:
                            body_text = page.inner_text("body")
                        except Exception:
                            body_text = ""
                        body_lower = strip_accents(body_text).lower()

                        if home_norm in body_lower and away_norm in body_lower:
                            correct_found = True
                            break
                        else:
                            # go back
                            page.go_back()
                            page.wait_for_timeout(2000)
                            # re-search
                            search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
                            if search_input:
                                search_input.fill(home_raw)
                                search_input.press("Enter")
                                page.wait_for_timeout(5000)
                            else:
                                break
                    if correct_found:
                        break

                if not correct_found:
                    report_lines.append("❌ Correct match not found on Betpawa")
                    continue

                # Parse Betpawa markets
                bet_markets = parse_betpawa_page(body_text)

                # For each Betpawa market, compute canonical key and compare
                matched_count = 0
                for bm in bet_markets:
                    ck = canonical_key_from_betpawa(bm)
                    if not ck or ck not in pinnacle_index:
                        continue
                    pm = pinnacle_index[ck]
                    pinnacle_selections = pm.get("selections", [])
                    bet_selections = bm["selections"]

                    if len(bet_selections) != len(pinnacle_selections):
                        continue

                    # Align by position (betpawa order should match pinnacle order)
                    evs = []
                    for (label, bet_odd), ps in zip(bet_selections, pinnacle_selections):
                        true_prob = ps.get("true_prob")
                        if true_prob is None:
                            continue
                        ev = (true_prob * bet_odd) - 1
                        evs.append((label, bet_odd, true_prob, ev))

                    if not evs:
                        continue

                    report_lines.append(f"📌 {bm['header']} (canonical {ck})")
                    for label, bet_odd, tp, ev in evs:
                        flag = "🚀" if ev > MIN_EV else ""
                        report_lines.append(f"   {label}: Betpawa {bet_odd} | TP {tp:.2f} | EV {ev*100:+.1f}% {flag}")
                    matched_count += 1

                if matched_count == 0:
                    report_lines.append("ℹ️ No strict matches found.")

            except Exception as e:
                report_lines.append(f"⚠️ Exception: {e}")

        browser.close()

    full_report = "\n".join(report_lines)
    send_telegram(full_report)

if __name__ == "__main__":
    main()
