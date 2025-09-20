from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"

TARGETS = [("Mon", "20:00"), ("Thu", "20:00"), ("Sun", "14:00")]
DURATION_VALUE = "1,5"  # 1,5 uur

def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int = 2) -> datetime:
    base_date = datetime(base.year, base.month, base.day)
    days_ahead = (weekday_idx - base_date.weekday() + 7) % 7
    days_ahead += 7 * (weeks_ahead - 1)
    return base_date + timedelta(days=days_ahead)

def weekday_idx(lbl: str) -> int:
    return {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}[lbl]

def log(msg): print("[LOG]", msg)

def main():
    today = datetime.now()
    plan = [(next_weekday(today, weekday_idx(w), 2), w, hhmm) for (w, hhmm) in TARGETS]

    with sync_playwright() as p:
        # headless=False でブラウザ表示、デフォルトタイムアウトは短め
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(4000)

        try:
            log(f"Open: {BOOK_URL}")
            page.goto(BOOK_URL, wait_until="domcontentloaded")

            # ---- Duration: 「Hoe lang wilt u reserveren?」を選択 ----
            log("Try select duration by label")
            try:
                page.get_by_label("Hoe lang wilt u reserveren?").select_option(DURATION_VALUE)
                log("Selected duration via label")
            except PWTimeout:
                log("Label not found, fallback to 1st <select>")
                try:
                    page.locator("select").nth(0).select_option(DURATION_VALUE)
                    log("Selected duration via fallback select[0]")
                except Exception as e:
                    log(f"Duration select failed: {e}")

            # ---- Activiteit（任意）: 'zaalvoetbal' があれば選択 ----
            log("Try select Activiteit if present")
            try:
                act = page.get_by_label("Activiteit")
                opts = act.locator("option")
                for i in range(opts.count()):
                    t = opts.nth(i).inner_text().lower()
                    if "zaalvoetbal" in t:
                        act.select_option(opts.nth(i).get_attribute("value"))
                        log("Selected Activiteit: zaalvoetbal")
                        break
            except PWTimeout:
                log("Activiteit label not found (skip)")

            results = []
            for d, wlbl, start_hhmm in plan:
                iso = d.strftime("%Y-%m-%d")
                log(f"---- Check {iso} {wlbl} {start_hhmm} ----")

                # 日付入力（input[type=date] 直接 or ラベル指定）
                ok_date = False
                try:
                    page.get_by_label("Voor wanneer?").fill(iso)
                    ok_date = True
                    log("Filled date via label")
                except PWTimeout:
                    log("Date label not found, try input[type=date]")
                    try:
                        page.fill("input[type='date']", iso)
                        ok_date = True
                        log("Filled date via input[type=date]")
                    except Exception as e:
                        log(f"Date fill failed: {e}")

                available = False
                label_text = ""
                if ok_date:
                    # 時刻セレクトを特定
                    time_sel = None
                    try:
                        time_sel = page.get_by_label("Welke tijd")
                        log("Found time select via label")
                    except PWTimeout:
                        log("Time label not found, search select with ':' text")
                        all_sel = page.locator("select")
                        for i in range(all_sel.count()):
                            inner = all_sel.nth(i).inner_text()
                            if ":" in inner:
                                time_sel = all_sel.nth(i)
                                log(f"Guessed time select: select[{i}]")
                                break

                    if time_sel:
                        opts = time_sel.locator("option")
                        log(f"Time options count: {opts.count()}")
                        for i in range(opts.count()):
                            t = opts.nth(i).inner_text().strip()
                            if t.startswith(start_hhmm):
                                try:
                                    val = opts.nth(i).get_attribute("value")
                                    time_sel.select_option(val)
                                    available = True
                                    label_text = t
                                    log(f"Matched time option: {t}")
                                    break
                                except Exception as e:
                                    log(f"Select time option failed: {e}")
                        if not available:
                            log("No matching time option found")

                results.append((iso, wlbl, start_hhmm, available, label_text))

            for iso, wlbl, hhmm, ok, txt in results:
                print(f"{iso} ({wlbl}) {hhmm} → {'Available ✅' if ok else 'Not available ❌'} {('['+txt+']') if txt else ''}")

        finally:
            # デバッグが見やすいように少し待ってから閉じる
            page.wait_for_timeout(800)
            browser.close()

if __name__ == "__main__":
    main()
