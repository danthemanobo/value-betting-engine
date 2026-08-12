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

def get_real_utc_now():
    try:
        resp = requests.get("http://worldtimeapi.org/api/timezone/Etc/UTC", timeout=5)
        if resp.status_code == 200:
            return datetime.fromisoformat(resp.json()["datetime"]).replace(tzinfo=timezone.utc)
    except:
        pass
    return datetime.now(timezone.utc)

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def normalize(name):
    return re.sub(r'\s+', ' ', strip_accents(name).replace('-', ' ')).strip()

def parse_odds_from_page(page):
    odds = {"home": None, "draw": None, "away": None}
    try:
        price_elements = page.query_selector_all("span[class*='price'], span[class*='odd'], button[class*='price']")
        if not price_elements:
            numbers = page.evaluate("""() => {
                const res = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (/^\\d+\\.\\d{2}$/.test(t)) res.push(t);
                }
                return res;
            }""")
            numbers = [float(x) for x in numbers if float(x) > 1.0]
            if len(numbers) >= 3:
                odds = {"home": numbers[0], "draw": numbers[1], "away": numbers[2]}
        else:
            prices = []
            for el in price_elements:
                txt = el.inner_text().strip()
                try:
                    val = float(txt)
                    if val > 1.0:
                        prices.append(val)
                except:
                    continue
            if len(prices) >= 3:
                odds = {"home": prices[0], "draw": prices[1], "away": prices[2]}
    except Exception as e:
        print(f"Odds extraction error: {e}")
    return odds

def get_fresh_search_input(page):
    search_icon = page.query_selector("button[aria-label*='search' i]")
    if search_icon:
        search_icon.click()
        page.wait_for_timeout(1500)
    return page.query_selector('input[type="search"], input[type="text"], input:not([type])')

def get_match_title(page):
    """Try to extract a heading/title that indicates the two teams."""
    selectors = [
        "h1", "h2", "div[class*='title']", "div[class*='heading']",
        "span[class*='team']", "div[class*='team']"
    ]
    for sel in selectors:
        el = page.query_selector(sel)
        if el:
            txt = el.inner_text().strip()
            if len(txt) > 3:
                return txt
    return "Unknown title"

def search_and_extract(page, home_norm):
    """Search for home team, click first non-simulated football result, return (found, url, odds, title, msg)."""
    # Try a few search terms
    terms = [home_norm]
    if ' ' in home_norm:
        terms.append(home_norm.split(' ')[0])
    for term in terms:
        input_el = get_fresh_search_input(page)
        if not input_el:
            return False, None, None, "No search input", "No input"
        input_el.click()
        input_el.fill("")
        page.wait_for_timeout(200)
        input_el.fill(term)
        page.wait_for_timeout(300)
        input_el.press("Enter")
        page.wait_for_timeout(4000)

        result_elements = page.query_selector_all("div[class*='event']")
        for elem in result_elements:
            text = elem.inner_text()
            if 'eFootball' in text or 'Simulated' in text or 'Esoccer' in text:
                continue
            # Only require home team to be present (fuzzy)
            if fuzz.partial_ratio(home_norm, strip_accents(text)) > 60:
                anchor = elem.query_selector("a")
                if anchor:
                    href = anchor.get_attribute("href")
                    if href:
                        full_url = "https://www.betpawa.ng" + href if href.startswith('/') else href
                        page.goto(full_url, timeout=30000, wait_until="networkidle")
                        page.wait_for_timeout(5000)
                        odds = parse_odds_from_page(page)
                        title = get_match_title(page)
                        return True, full_url, odds, title, f"Found with term: {term}"
    return False, None, None, "No match after search", "No title"

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    alerts = []
    debug_lines = []

    fs_matches = db.collection("matches").where("kickoff", ">=", now_utc.isoformat()).where("kickoff", "<", window_end.isoformat()).stream()
    matches_list = []
    for doc in fs_matches:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        matches_list.append(data)

    if not matches_list:
        send_telegram("ℹ️ No Pinnacle matches in window for Betpawa comparison.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        for match in matches_list:
            home_raw = match.get("home", "")
            away_raw = match.get("away", "")
            home_norm = normalize(home_raw)
            away_norm = normalize(away_raw)
            debug_line = ""
            try:
                found, url, odds, title, msg = search_and_extract(page, home_norm)
                if not found:
                    # Capture search results for diagnosis
                    result_elements = page.query_selector_all("div[class*='event']")
                    sample = []
                    for e in result_elements[:2]:
                        sample.append(e.inner_text()[:150])
                    sample_text = "\n".join(sample) if sample else "No results"
                    debug_line = f"❌ Not found: {home_raw} vs {away_raw}\nReason: {msg}\nSample results:\n{sample_text}"
                else:
                    true_probs = match.get("true_probs_1x2")
                    debug_line = f"✅ {home_raw} vs {away_raw}\nURL: {url}\nTitle: {title}\nOdds: {odds['home']}/{odds['draw']}/{odds['away']}"
                    if true_probs:
                        ev_home = (true_probs["home"] * odds["home"]) - 1
                        ev_draw = (true_probs["draw"] * odds["draw"]) - 1
                        ev_away = (true_probs["away"] * odds["away"]) - 1
                        debug_line += f"\nTP: {true_probs['home']:.2f}/{true_probs['draw']:.2f}/{true_probs['away']:.2f}\nEV%: {ev_home*100:.1f}/{ev_draw*100:.1f}/{ev_away*100:.1f}"
                        if ev_home > MIN_EV:
                            alerts.append(f"⚽ {home_raw} vs {away_raw}\n1X2 Home @ {odds['home']} (EV +{ev_home*100:.1f}%)\nBetpawa")
                        if ev_draw > MIN_EV:
                            alerts.append(f"⚽ {home_raw} vs {away_raw}\n1X2 Draw @ {odds['draw']} (EV +{ev_draw*100:.1f}%)\nBetpawa")
                        if ev_away > MIN_EV:
                            alerts.append(f"⚽ {home_raw} vs {away_raw}\n1X2 Away @ {odds['away']} (EV +{ev_away*100:.1f}%)\nBetpawa")
                    else:
                        debug_line += "\n⚠️ Missing true_probs_1x2"
                    # Return to events page for next search
                    page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                    page.wait_for_timeout(2000)
            except Exception as e:
                debug_line = f"⚠️ Exception for {home_raw} vs {away_raw}: {e}"
            debug_lines.append(debug_line)

        browser.close()

    report = f"🔍 Betpawa search-based scraper:\n- Matches processed: {len(matches_list)}\n"
    if alerts:
        report += f"\n🚀 +EV Alerts ({len(alerts)}):\n" + "\n".join(alerts[:10])
    else:
        report += "\nℹ️ No +EV bets found."
    report += "\n\n📋 Detailed Debug:\n" + "\n\n".join(debug_lines)
    send_telegram(report)

if __name__ == "__main__":
    main()
