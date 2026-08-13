import os, json, re, requests, unicodedata
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
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

def parse_pinnacle_key(key):
    """Extract info from Pinnacle key."""
    parts = key.split(';')
    if len(parts) < 3:
        return None
    period = parts[1]
    code = parts[2]
    info = {"period": period, "type": None, "line": None, "side": None}
    if code == 'm':
        info["type"] = "1x2"
    elif code == 'ou':
        info["type"] = "total"
        if len(parts) > 3:
            info["line"] = parts[3]
    elif code == 'tt':
        info["type"] = "team_total"
        if len(parts) > 3:
            info["line"] = parts[3]
        if len(parts) > 4:
            info["side"] = parts[4]
    else:
        return None
    return info

def canonical_key_from_pinnacle(info):
    period = info.get("period", "0")
    type_ = info.get("type")
    line = info.get("line")
    if type_ == "1x2":
        return f"1x2_{period}"
    elif type_ == "total":
        return f"total_{period}_{line}"
    elif type_ == "team_total":
        side = info.get("side")
        return f"team_total_{period}_{side}_{line}"
    return None

def parse_focused_markets(body_text):
    """
    Extract only 1X2 Full Time and Over/Under 2.5 Full Time.
    Returns dict with keys '1x2' and 'ou_2_5', each containing selections list.
    """
    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
    markets = {'1x2': None, 'ou_2_5': None}

    i = 0
    while i < len(lines):
        line = lines[i]
        if '1X2 | Full Time' in line:
            # Next three lines should be label, odds, label, odds, label, odds
            try:
                if i+6 <= len(lines):
                    home_label = lines[i+1]
                    home_odd = float(lines[i+2])
                    draw_label = lines[i+3]
                    draw_odd = float(lines[i+4])
                    away_label = lines[i+5]
                    away_odd = float(lines[i+6])
                    if home_label == '1' and draw_label == 'X' and away_label == '2':
                        markets['1x2'] = [('home', home_odd), ('draw', draw_odd), ('away', away_odd)]
            except:
                pass
            i += 1
            continue

        if 'Over/Under | Full Time' in line:
            # We'll search subsequent lines for "Over 2.5" and "Under 2.5"
            j = i + 1
            while j < len(lines) and '|' not in lines[j]:
                if lines[j].strip().lower() == 'over 2.5':
                    try:
                        over_odd = float(lines[j+1])
                        if j+2 < len(lines) and lines[j+2].strip().lower() == 'under 2.5':
                            under_odd = float(lines[j+3])
                            markets['ou_2_5'] = [('Over', over_odd), ('Under', under_odd)]
                    except:
                        pass
                j += 1
            i = j
            continue

        i += 1

    return markets

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

            # Build Pinnacle index for just 1x2 and total_0_2.5
            pinnacle_index = {}
            for pm in match.get("markets", []):
                key = pm.get("key")
                info = parse_pinnacle_key(key)
                if info:
                    ck = canonical_key_from_pinnacle(info)
                    if ck:
                        pinnacle_index[ck] = pm

            report_lines.append(f"\n⚽ {home_raw} vs {away_raw}")

            try:
                # Navigate and search for home team
                page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(3000)

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
                            page.go_back()
                            page.wait_for_timeout(2000)
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

                # Parse focused markets
                bet_markets = parse_focused_markets(body_text)

                # 1X2 Full Time
                if bet_markets['1x2'] and '1x2_0' in pinnacle_index:
                    pm = pinnacle_index['1x2_0']
                    bet_selections = bet_markets['1x2']
                    pinnacle_selections = pm.get("selections", [])
                    if len(bet_selections) == len(pinnacle_selections):
                        evs = []
                        labels = ['1', 'X', '2']
                        for label, (sel_label, bet_odd), ps in zip(labels, bet_selections, pinnacle_selections):
                            tp = ps.get("true_prob")
                            if tp is None:
                                continue
                            ev = (tp * bet_odd) - 1
                            evs.append((label, bet_odd, tp, ev))
                        if evs:
                            report_lines.append("📌 1X2 | Full Time")
                            for label, bet_odd, tp, ev in evs:
                                flag = "🚀" if ev > MIN_EV else ""
                                report_lines.append(f"   {label}: Betpawa {bet_odd} | TP {tp:.2f} | EV {ev*100:+.1f}% {flag}")

                # Over/Under 2.5 Full Time
                if bet_markets['ou_2_5'] and 'total_0_2.5' in pinnacle_index:
                    pm = pinnacle_index['total_0_2.5']
                    bet_selections = bet_markets['ou_2_5']
                    pinnacle_selections = pm.get("selections", [])
                    if len(bet_selections) == len(pinnacle_selections):
                        evs = []
                        labels = ['Over', 'Under']
                        for label, (sel_label, bet_odd), ps in zip(labels, bet_selections, pinnacle_selections):
                            tp = ps.get("true_prob")
                            if tp is None:
                                continue
                            ev = (tp * bet_odd) - 1
                            evs.append((label, bet_odd, tp, ev))
                        if evs:
                            report_lines.append("📌 Over/Under 2.5 | Full Time")
                            for label, bet_odd, tp, ev in evs:
                                flag = "🚀" if ev > MIN_EV else ""
                                report_lines.append(f"   {label}: Betpawa {bet_odd} | TP {tp:.2f} | EV {ev*100:+.1f}% {flag}")

                if not bet_markets['1x2'] and not bet_markets['ou_2_5']:
                    report_lines.append("ℹ️ No supported markets found on Betpawa page.")

            except Exception as e:
                report_lines.append(f"⚠️ Exception: {e}")

        browser.close()

    full_report = "\n".join(report_lines)
    send_telegram(full_report)

if __name__ == "__main__":
    main()
