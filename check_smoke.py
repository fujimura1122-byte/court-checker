from playwright.sync_api import sync_playwright

URL = "https://avo.hta.nl/uithoorn/Accommodation/Detail/106"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")

        title = page.title()
        body_text = page.inner_text("body")

        print("PAGE TITLE:", title)
        print("FORM LABELS PRESENT:",
              all(k in body_text for k in ["Selecteer dag", "Welk dagdeel", "Hoe lang", "Activiteit"]))
        print("HAS 'Beschikbare tijdvakken':", "Beschikbare tijdvakken" in body_text)

        browser.close()

if __name__ == "__main__":
    main()
