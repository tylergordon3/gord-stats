from playwright import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    captured = []

    def handle_response(resp):
        if "scoreboard" in resp.url or "odds" in resp.url:
            try:
                captured.append(resp.json())
            except:
                pass

    page.on("response", handle_response)

    page.goto("https://www.cbssports.com/college-basketball/scoreboard/")
    page.wait_for_timeout(5000)

    browser.close()

print(len(captured))
