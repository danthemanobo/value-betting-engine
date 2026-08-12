import os, json, requests, re
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

        # Extract top league links (real leagues only)
        links = page.eval_on_selector_all(
            "a",
            """els => els
                .filter(e => e.href && e.href.includes('/soccer/') && e.href.includes('/matchups/'))
                .filter(e => !e.href.includes('/matchups/highlights/') && !e.href.includes('/matchups/live/') && !e.href.includes('/matchups/futures/'))
                .map(e => ({href: e.href, text: e.innerText.trim()}))
                .filter(x => x.text.length > 0)
                .slice(0, 10)"""
        )
        if not links:
            send_telegram_plain("No leagues found.")
            browser.close()
            return

        # Visit first real league
        first_league = links[0]
        debug_info.append(f"Visiting: {first_league['text']}")
        page.goto(first_league['href'], timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Scroll to load matches
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(1000)

        # Scan all elements for decimal odds text
        odds_elements = page.evaluate("""() => {
            const results = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            const seen = new Set();
            while (walker.nextNode()) {
                const text = walker.currentNode.textContent.trim();
                if (/^\\d+\\.\\d{2}$/.test(text)) {
                    const el = walker.currentNode.parentElement;
                    if (!el) continue;
                    // climb up to a container that has multiple odds
                    let ancestor = el;
                    for (let i=0; i<4; i++) {
                        if (ancestor.parentElement) ancestor = ancestor.parentElement;
                    }
                    const key = ancestor.outerHTML;
                    if (!seen.has(key)) {
                        seen.add(key);
                        results.push({
                            text: text,
                            tag: el.tagName,
                            class: el.className || '',
                            ancestorHTML: ancestor.outerHTML.slice(0, 1000)
                        });
                    }
                }
            }
            return results.slice(0, 5); // first 5 unique
        }""")

        if odds_elements:
            debug_info.append(f"Found {len(odds_elements)} unique odds elements (showing first 5).")
            for i, item in enumerate(odds_elements, 1):
                debug_info.append(f"\n--- Odds element {i} ---")
                debug_info.append(f"Text: {item['text']}")
                debug_info.append(f"Tag: {item['tag']}")
                debug_info.append(f"Class: {item['class']}")
                debug_info.append(f"Ancestor HTML:\n{item['ancestorHTML']}")
        else:
            debug_info.append("No decimal odds found on the page. The odds might require clicking a match or are not loaded.")
            # Try clicking the first match element to see if odds appear
            first_match = page.query_selector("div[class*='match']")
            if first_match:
                first_match.click()
                page.wait_for_timeout(3000)
                body_text = page.inner_text("body")[:1000]
                debug_info.append(f"After click body sample:\n{body_text}")

        browser.close()

    full_msg = "🔍 Pinnacle Odds Hunt:\n" + "\n\n".join(debug_info)
    send_telegram_plain(full_msg[:12000])
    print("Debug sent.")

if __name__ == "__main__":
    main()
