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
STAKE = 100.0  # theoretical for paper trading

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

def american_to_decimal(american):
    if american > 0:
        return round(1 + american/100, 3)
    else:
        return round(1 + 100/abs(american), 3)

# ========== BETPAWA PAGE PARSING ==========
def parse_betpawa_markets(page_text):
    """
    Extract markets from Betpawa match page text.
    Returns list of dicts: {name, selections: [{name, odds}]}
    """
    lines = page_text.split('\n')
    markets = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Market headers usually contain "| Full Time" or "| First Half", etc.
        if '|' in line and ('Full Time' in line or '1st Half' in line or '2nd Half' in line):
            market_name = line.strip()
            i += 1
            selections = []
            # Collect until next market header or empty
            while i < len(lines):
                l = lines[i].strip()
                if not l:
                    i += 1
                    continue
                # If we hit another market header, break
                if '|' in l and ('Full Time' in l or '1st Half' in l or '2nd Half' in l):
                    break
                # Try to match selection + odds pattern: selection label (optional) then number
                # We expect lines like: "Over" then next line "1.92", or "1" then next "2.62"
                # We'll try to pair a label with a number
                # If line is a decimal number and previous line was a label
                # Or if line itself is a label like "Home", "Draw", "Away", etc.
                # Simpler: collect all tokens and group by three or two numbers.
                # We'll just try to find decimal numbers after the header until next header.
                # For now, just collect all decimal numbers and assume order based on market type.
                # This is a placeholder; we'll refine after seeing actual page structure.
                l2 = None
                if i+1 < len(lines):
                    l2 = lines[i+1].strip()
                # Check if current line is a known selection and next line is decimal
                if l in ('1', 'X', '2', 'Over', 'Under', 'Yes', 'No', '1X', 'X2', '12') and l2 and re.match(r'^\d+\.\d+$', l2):
                    selections.append((l, float(l2)))
                    i += 2
                else:
                    # Try to see if current line itself is a decimal number
                    if re.match(r'^\d+\.\d+$', l):
                        # We don't know label, use index as label
                        selections.append((f"selection_{len(selections)+1}", float(l)))
                        i += 1
                    else:
                        i += 1
            if selections:
                markets.append({
                    "name": market_name,
                    "selections": selections
                })
        else:
            i += 1
    return markets

def match_pinnacle_market(bet_name, pinnacle_markets):
    """Find best matching Pinnacle market by name."""
    # Normalize both sides
    bet_norm = normalize(bet_name)
    best = None
    best_score = 0
    for pm in pinnacle_markets:
        pm_name = pm.get("market_name", "")
        pm_norm = normalize(pm_name)
        # Use fuzzy partial ratio
        score = fuzz.partial_ratio(bet_norm, pm_norm)
        if score > best_score and score > 60:
            best_score = score
            best = pm
    return best, best_score

def extract_selections_from_betpawa(selections, market_type):
    """Convert Betpawa selection list to ordered dict based on expected market type."""
    # This will be refined after we know actual order.
    # For now, just return as is.
    return selections

def main():
    now_utc = datetime.now(timezone.utc)
    # Fetch all stored Pinnacle matches (or limit for testing)
    matches_ref = db.collection("matches").limit(3).stream()
    matches_list = []
    for doc in matches_ref:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        if "markets" in data:
            matches_list.append(data)

    if not matches_list:
        send_telegram("ℹ️ No stored Pinnacle matches found in Firestore.")
        return

    report_lines = []
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
                # Go to Betpawa events page
                page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(3000)

                # Click search icon
                search_icon = page.query_selector("button[aria-label*='search' i]")
                if search_icon:
                    search_icon.click()
                    page.wait_for_timeout(1500)

                search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
                if not search_input:
                    report_lines.append("❌ Search input missing")
                    continue

                search_input.click()
                search_input.fill("")
                page.wait_for_timeout(200)
                search_input.fill(home_raw)
                page.wait_for_timeout(500)
                search_input.press("Enter")
                page.wait_for_timeout(5000)

                # Find first football result
                result_elements = page.query_selector_all("div[class*='event']")
                clicked = False
                for elem in result_elements:
                    text = elem.inner_text()
                    text_lower = strip_accents(text).lower()
                    if 'football' not in text_lower:
                        continue
                    # Check home team appears (fuzzy)
                    if fuzz.partial_ratio(home_norm, strip_accents(text_lower)) > 60:
                        # Click the element directly
                        elem.click()
                        page.wait_for_timeout(5000)
                        clicked = True
                        break
                if not clicked:
                    report_lines.append("❌ Could not click match")
                    continue

                # Now we are on match page. Get full page text
                page_text = page.inner_text("body")
                bet_markets = parse_betpawa_markets(page_text)

                # For each Betpawa market, try to match with Pinnacle and compute EV
                matched_count = 0
                for bet_market in bet_markets:
                    bet_name = bet_market["name"]
                    bet_selections = bet_market["selections"]
                    pinnacle_market, score = match_pinnacle_market(bet_name, pinnacle_markets)
                    if not pinnacle_market:
                        continue

                    # Extract true probabilities
                    true_probs = [s["true_prob"] for s in pinnacle_market["selections"]]
                    decimal_odds = [s["decimal"] for s in pinnacle_market["selections"]]

                    # We need to align Betpawa selections with Pinnacle selections order.
                    # For now assume order matches; we'll improve later.
                    evs = []
                    for (label, bet_odd), true_prob in zip(bet_selections, true_probs):
                        ev = (true_prob * bet_odd) - 1
                        evs.append((label, bet_odd, true_prob, ev))

                    report_lines.append(f"📌 {bet_name} (match score {score})")
                    for label, bet_odd, tp, ev in evs:
                        flag = "🚀" if ev > MIN_EV else ""
                        report_lines.append(f"   {label}: Betpawa {bet_odd} | TrueProb {tp:.2f} | EV {ev*100:+.1f}% {flag}")
                    matched_count += 1

                if matched_count == 0:
                    report_lines.append("No markets matched.")

            except Exception as e:
                report_lines.append(f"⚠️ Exception: {e}")

        browser.close()

    # Send report
    full_report = "\n".join(report_lines)
    send_telegram(full_report)

if __name__ == "__main__":
    main()
