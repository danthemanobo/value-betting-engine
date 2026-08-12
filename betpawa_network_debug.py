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

def main():
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Listen to network responses
        def on_response(response):
            try:
                url = response.url
                # Only care about XHR/fetch that likely return JSON
                if response.request.resource_type in ("xhr", "fetch"):
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type or "application/json" in content_type:
                        # Capture only URLs that look like API endpoints
                        if any(keyword in url.lower() for keyword in ["api", "event", "odds", "sport", "match"]):
                            body = response.text()
                            # Keep a snippet for inspection
                            snippet = body[:500]
                            captured.append({
                                "url": url,
                                "status": response.status,
                                "content_type": content_type,
                                "snippet": snippet
                            })
            except Exception as e:
                pass

        page.on("response", on_response)

        # Navigate to Betpawa events page
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Scroll a few times to trigger lazy loading and API calls
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        browser.close()

    # Filter out duplicates and sort by URL
    seen_urls = set()
    unique_captures = []
    for cap in captured:
        if cap["url"] not in seen_urls:
            seen_urls.add(cap["url"])
            unique_captures.append(cap)

    if not unique_captures:
        send_telegram_plain("No API-like network requests captured. Try scrolling more or different page.")
        return

    # Build message (limit to first 10 unique endpoints)
    lines = [f"Captured {len(unique_captures)} API endpoints. Showing first 10:"]
    for idx, cap in enumerate(unique_captures[:10], 1):
        lines.append(f"\n{idx}. URL: {cap['url']}")
        lines.append(f"Status: {cap['status']}")
        lines.append(f"Content-Type: {cap['content_type']}")
        lines.append(f"Snippet: {cap['snippet'][:300]}")

    full_msg = "🔍 Betpawa Network Debug:\n" + "\n".join(lines)
    send_telegram_plain(full_msg[:12000])

if __name__ == "__main__":
    main()
