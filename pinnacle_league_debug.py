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
            resp = requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"Telegram error on chunk {i//max_len}: {e}")

def main():
    debug_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Load leagues page
        page.goto("https://www.pinnacle.com/en/soccer/leagues/", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Extract top league links, filter out highlights/live/futures
        links = page.eval_on_selector_all(
            "a",
            """els => els
                .filter(e => e.href && e.href.includes('/soccer/') && e.href.includes('/matchups/'))
                .filter(e => !e.href.includes('/matchups/highlights/') && !e.href.includes('/matchups/live/') && !e.href.includes('/matchups/futures/'))
                .map(e => ({href: e.href, text: e.innerText.trim()}))
                .filter(x => x.text.length > 0)
                .slice(0, 10)"""
        )
        debug_info.append(f"Filtered league links: {len(links)}")
        for i, l in enumerate(links[:10], 1):
            debug_info.append(f"{i}. {l['text']} -> {l['href']}")

        if not links:
            send_telegram_plain("🔍 Pinnacle League Debug:\n" + "\n".join(debug_info))
            browser.close()
            return

        # Visit first real league
        first_league = links[0]
        debug_info.append(f"\nVisiting first real league: {first_league['text']}")
        page.goto(first_league['href'], timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Scroll to load matches
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(1000)

        # Find match elements (metadata)
        match_elements = page.query_selector_all("div[class*='match']")
        debug_info.append(f"Found {len(match_elements)} match elements.")

        if match_elements:
            # Get the parent element of the first match, which likely contains odds
            first_match = match_elements[0]
            parent_html = first_match.evaluate("el => el.parentElement.outerHTML")
            # Also get all numeric text within parent
            numeric_texts = first_match.evaluate(
                """el => {
                    const parent = el.parentElement;
                    const nums = [];
                    const walker = document.createTreeWalker(parent, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        const t = walker.currentNode.textContent.trim();
                        if (/^\d+\.\d+$/.test(t)) nums.push(t);
                    }
                    return nums;
                }"""
            )
            debug_info.append(f"Numeric odds inside parent: {numeric_texts}")
            debug_info.append(f"Parent outerHTML (full):\n{parent_html[:10000]}")

        else:
            body_text = page.inner_text("body")[:1000]
            debug_info.append(f"No match elements. Body snippet:\n{body_text}")

        browser.close()

    full_message = "🔍 Pinnacle League Debug:\n" + "\n\n".join(debug_info)
    send_telegram_plain(full_message[:15000])  # will be split into chunks
    print("Debug sent.")

if __name__ == "__main__":
    main()
