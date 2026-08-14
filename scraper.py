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
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def normalize(name):
    return re.sub(r'\s+', ' ', strip_accents(name).replace('-', ' ')).strip().lower()

def exact_team_match(name, text_lower):
    """Check if team name appears as a whole word/phrase."""
    # Escape regex special characters and use word boundaries
    pattern = r'(?<!\w)' + re.escape(normalize(name)) + r'(?!\w)'
    return re.search(pattern, text_lower) is not None

def parse_1x2(body_text):
    """Extract 1X2 Full Time odds from Betpawa page text."""
    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
    for i, line in enumerate(lines):
        if line == "1X2 | Full Time":
            if i+6 <= len(lines):
                try:
                    home_odd = float(lines[i+2])
                    draw_odd = float(lines[i+4])
                    away_odd = float(lines[i+6])
                    if lines[i+1] == '1' and lines[i+3] == 'X' and lines[i+5] == '2':
                        return [('home', home_odd), ('draw', draw_odd), ('away', away_odd)]
                except:
                    pass
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

    matches_list = matches_list[:3]

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

            # Find Pinnacle 1X2 true probabilities
            true_probs = None
            for pm in match.get("markets", []):
                if pm.get("key") == "s;0;m":
                    true_probs = [s["true_prob"] for s in pm.get("selections", [])]
                    break
            if not true_probs:
                continue

            report_lines.append(f"\n⚽ {home_raw} vs {away_raw}")

            try:
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

                        # Strict exact match
                        if exact_team_match(home_raw, body_lower) and exact_team_match(away_raw, body_lower):
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

                bet_1x2 = parse_1x2(body_text)

                if bet_1x2 and len(bet_1x2) == 3:
                    evs = []
                    labels = ['1', 'X', '2']
                    for label, (sel_name, bet_odd), tp in zip(labels, bet_1x2, true_probs):
                        ev = (tp * bet_odd) - 1
                        evs.append((label, bet_odd, tp, ev))
                    report_lines.append("📌 1X2 | Full Time")
                    for label, bet_odd, tp, ev in evs:
                        flag = "🚀" if ev > MIN_EV else ""
                        report_lines.append(f"   {label}: Betpawa {bet_odd} | TP {tp:.2f} | EV {ev*100:+.1f}% {flag}")
                else:
                    report_lines.append("❌ 1X2 market not found on Betpawa page")

            except Exception as e:
                report_lines.append(f"⚠️ Exception: {e}")

        browser.close()

    full_report = "\n".join(report_lines)
    send_telegram(full_report)

if __name__ == "__main__":
    main()
