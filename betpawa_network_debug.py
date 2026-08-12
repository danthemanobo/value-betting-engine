import os, json, requests
from playwright.sync_api import sync_playwright

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

def is_sports_data_response(url, content_type, body):
    # Exclude known unrelated endpoints
    excluded_keywords = [
        "sentry", "strapi", "brand/v1/countries",
        "preference/v1", "maze.co", "announcements",
        "jurisdictions", "pages?", "logo"
    ]
    if any(k in url for k in excluded_keywords):
        return False

    if "application/json" not in content_type:
        return False

    # Look for strong sports-data indicators
    indicators = [
        '"event"', '"events"', '"fixture"', '"homeTeam"',
        '"awayTeam"', '"teams"', '"odds"', '"outcomes"',
        '"market"', '"matchId"', '"categoryId"', '"competition"',
        '"sport"', '"home"', '"away"'
    ]
    return any(ind in body for ind in indicators)

def main():
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(response):
            try:
                if response.request.resource_type not in ("xhr", "fetch"):
                    return
                url = response.url
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    return
                body = response.text()
                if is_sports_data_response(url, content_type, body):
                    captured.append({
                        "url": url,
                        "status": response.status,
                        "snippet": body[:500]
                    })
            except Exception:
                pass

        page.on("response", on_response)

        # Navigate to Betpawa 1X2 events
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Scroll more aggressively to trigger lazy loading
        for _ in range(8):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        browser.close()

    # Deduplicate by URL
    seen = set()
    unique = []
    for cap in captured:
        if cap["url"] not in seen:
            seen.add(cap["url"])
            unique.append(cap)

    if not unique:
        send_telegram_plain("🔍 No sports-data API captured. Next: inspect __NEXT_DATA__ or GraphQL.")
        return

    lines = [f"Captured {len(unique)} sports-data endpoints. Showing first 10:"]
    for idx, cap in enumerate(unique[:10], 1):
        lines.append(f"\n{idx}. URL: {cap['url']}")
        lines.append(f"Status: {cap['status']}")
        lines.append(f"Snippet: {cap['snippet'][:350]}")

    full_msg = "🔍 Betpawa Sports API Debug:\n" + "\n".join(lines)
    send_telegram_plain(full_msg[:12000])

if __name__ == "__main__":
    main()
