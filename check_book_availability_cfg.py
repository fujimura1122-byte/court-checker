import json
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"
CFG = Path("slots.json")

def weekday_index(lbl: str) -> int:
    return {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}[lbl]

def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int) -> datetime:
    base_date = datetime(base.year, base.month, base.day)
    days_ahead = (weekday_idx - base_date.weekday() + 7) % 7
    days_ahead += 7 * (weeks_ahead - 1)
    return base_date + timedelta(days=days_ahead)

def main():
    cfg = json.loads(Path(CFG).read_text(encoding="utf-8"))
    weeks_ahead = int(cfg.get("weeks_ahead", 2))
    duration_value = str(cfg.get("duration_value", "1,5"))
    targets = cfg["targets"]

    plan = []
    today = datetime.now()
    for t in targets:
        d = next_weekday(today, weekday_index(t["weekday"]), weeks_ahead)
        plan.append((d, t["weekday"], t["start"]))

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BOOK_URL, wait_until="domcontentloaded")

        # Duration
        try:
            page.get_by_label("Hoe lang wilt u reserveren?").select_option(duration_value)
        except Exception:
            sels = page.locator("select")
            try:
                sels.nth(0).select_option(duration_value)
            except Exception:
                pass

        # Activiteit（任意）：Zaalvoetbalがあれば選択
        try:
            act_sel = page.get_by_label("Activiteit")
            opts = act_sel.locator("option")
            for i in range(opts.count()):
                if "zaalvoetbal" in opts.nth(i).inner_text().lower():
                    act_sel.select_option(opts.nth(i).get_attribute("value"))
                    break
        except Exception:
            pass

        for d, wd_lbl, start_hhmm in plan:
            iso_date = d.strftime("%Y-%m-%d")

            # 日付入力
            ok_date = False
            try:
                page.get_by_label("Voor wanneer?").fill(iso_date)
                ok_date = True
            except Exception:
                try:
                    page.fill("input[type='date']", iso_date)
                    ok_date = True
                except Exception:
                    ok_date = False

            available = False
            label_text = ""

            if ok_date:
                # 時刻セレクト
                time_sel = None
                try:
                    time_sel = page.get_by_label("Welke tijd")
                except Exception:
                    all_selects = page.locator("select")
                    for i in range(all_selects.count()):
                        if ":" in all_selects.nth(i).inner_text():
                            time_sel = all_selects.nth(i)
                            break

                if time_sel:
                    options = time_sel.locator("option")
                    for i in range(options.count()):
                        t = options.nth(i).inner_text().strip()  # "20:00 - 21:30" など
                        if t.startswith(start_hhmm):
                            val = options.nth(i).get_attribute("value")
                            try:
                                time_sel.select_option(val)
                                available = True
                                label_text = t
                                break
                            except Exception:
                                pass

            results.append({
                "date": d.strftime("%Y-%m-%d"),
                "weekday": wd_lbl,
                "start": start_hhmm,
                "available": available,
                "slot_label": label_text
            })

        browser.close()

    for r in results:
        status = "Available ✅" if r["available"] else "Not available ❌"
        extra = f" [{r['slot_label']}]" if r["slot_label"] else ""
        print(f"{r['date']} ({r['weekday']}) {r['start']} → {status}{extra}")

if __name__ == "__main__":
    main()
