from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import re, time

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"

# チェック対象（再来週の 月・木・日）
TARGETS = [("Mon","20:00"), ("Thu","20:00"), ("Sun","14:00")]
WEEKS_AHEAD = 2

# オランダ語の月名（サイト表記に合わせる）
MONTHS_NL = [
    "januari","februari","maart","april","mei","juni",
    "juli","augustus","september","oktober","november","december"
]

def log(*a): print("[LOG]", *a, flush=True)

def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int) -> datetime:
    base_date = datetime(base.year, base.month, base.day)
    days_ahead = (weekday_idx - base_date.weekday() + 7) % 7
    days_ahead += 7 * (weeks_ahead - 1)
    return base_date + timedelta(days=days_ahead)

def wd_idx(lbl: str) -> int:
    return {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}[lbl]

def find_duration_select(page):
    """'1 uur','1,5 uur','2 uur'…の文字を含むselectを探す"""
    sels = page.locator("select")
    for i in range(sels.count()):
        txt = sels.nth(i).inner_text().lower()
        if re.search(r"\b\d+(?:,\d+)?\s*uur\b", txt):
            return sels.nth(i)
    return None

def find_time_select(page):
    """'15:00 - 16:30' のような時間レンジが並ぶselectを探す"""
    sels = page.locator("select")
    for i in range(sels.count()):
        txt = sels.nth(i).inner_text()
        if re.search(r"\b\d{2}:\d{2}\b", txt):
            return sels.nth(i)
    return None

def find_date_selects(page):
    """
    'Voor wanneer?' が select×3（日・月・年）で構成されている前提で、
    月名（オランダ語）が含まれるselect・数値年が並ぶselect・1..31のselectを検出して返す。
    戻り値: (sel_day, sel_month, sel_year) いずれかNone可
    """
    sel_day = sel_month = sel_year = None
    sels = page.locator("select")
    n = sels.count()

    # 候補を全部走査して特徴で判定
    for i in range(n):
        txt = sels.nth(i).inner_text().lower()

        # 月select判定
        if any(m in txt for m in MONTHS_NL):
            sel_month = sels.nth(i)
            continue

        # 年select判定（四桁の西暦が複数含まれていそう）
        if len(re.findall(r"\b20\d{2}\b", txt)) >= 2 or re.search(r"\b20\d{2}\b", txt):
            sel_year = sels.nth(i)
            continue

        # 日select判定（1～31の数字が羅列）
        if all(str(d) in txt for d in ( "1","2","3","10","20","31" )):
            sel_day = sels.nth(i)
            continue

    return sel_day, sel_month, sel_year

def set_date_by_selects(sel_day, sel_month, sel_year, target_date: datetime):
    """3セレクト(年・月・日)に値をセット"""
    # 年
    if sel_year:
        year_val = str(target_date.year)
        try:
            sel_year.select_option(year_val)
        except:
            pass
    # 月（表示テキスト一致→value取得してselect）
    if sel_month:
        month_label = MONTHS_NL[target_date.month - 1]
        opts = sel_month.locator("option")
        for i in range(opts.count()):
            if opts.nth(i).inner_text().strip().lower() == month_label:
                val = opts.nth(i).get_attribute("value") or month_label
                sel_month.select_option(val)
                break
    # 日
    if sel_day:
        day_val = str(target_date.day)
        try:
            sel_day.select_option(day_val)
        except:
            # valueが'01','02'形式の可能性
            try:
                sel_day.select_option(day_val.zfill(2))
            except:
                pass

def main():
    # 計画作成
    today = datetime.now()
    plan = []
    for wlbl, hhmm in TARGETS:
        d = next_weekday(today, wd_idx(wlbl), WEEKS_AHEAD)
        plan.append((d, wlbl, hhmm))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(4000)

        log("Open:", BOOK_URL)
        page.goto(BOOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(600)

        # Duration: 1,5 uur（無ければ 1 uur）
        dur = find_duration_select(page)
        if dur:
            txt = dur.inner_text()
            pick = "1,5 uur" if "1,5" in txt else "1 uur"
            picked = False
            opts = dur.locator("option")
            for i in range(opts.count()):
                lab = opts.nth(i).inner_text().strip()
                if lab == pick:
                    val = opts.nth(i).get_attribute("value") or lab
                    try:
                        dur.select_option(val); picked = True
                        log("Duration selected:", lab); break
                    except: pass
            if not picked:
                log("Duration NOT picked")
        else:
            log("Duration select not found")

        # 日付セレクト群を検出（Voor wanneer?）
        sel_day, sel_month, sel_year = find_date_selects(page)
        log("Date selects found:",
            "day" if sel_day else "-",
            "month" if sel_month else "-",
            "year" if sel_year else "-")

        results = []
        for d, wlbl, start in plan:
            log(f"---- Check {d.strftime('%Y-%m-%d')} ({wlbl}) {start} ----")
            if not (sel_day and sel_month and sel_year):
                results.append((d, wlbl, start, False, ""))
                continue

            # 年月日をセット
            set_date_by_selects(sel_day, sel_month, sel_year, d)
            page.wait_for_timeout(500)  # 反映待ち

            # 時刻セレクトを検出
            time_sel = find_time_select(page)
            if not time_sel:
                log("time select not found")
                results.append((d, wlbl, start, False, ""))
                continue

            # 希望開始時刻でマッチ
            opts = time_sel.locator("option")
            matched = False; label_text = ""
            for i in range(opts.count()):
                t = opts.nth(i).inner_text().strip()   # 例 "20:00 - 21:30"
                if t.startswith(start):
                    val = opts.nth(i).get_attribute("value") or t
                    try:
                        time_sel.select_option(val)
                        matched = True; label_text = t
                        log("Matched time:", t)
                        break
                    except: pass

            results.append((d, wlbl, start, matched, label_text))

        # 結果表示
        for (d, w, st, ok, lab) in results:
            print(f"{d.strftime('%Y-%m-%d')} ({w}) {st} → {'Available ✅' if ok else 'Not available ❌'} {('['+lab+']') if lab else ''}")

        page.wait_for_timeout(600)
        browser.close()

if __name__ == "__main__":
    main()
