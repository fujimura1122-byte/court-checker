from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import re, sys, time

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"

# 2週間後の 月/木/日（固定）をチェック
TARGETS = [("Mon","20:00"), ("Thu","20:00"), ("Sun","14:00")]
WEEKS_AHEAD = 2

def log(msg): 
    print(f"[LOG] {msg}"); sys.stdout.flush()

def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int = 2) -> datetime:
    base_date = datetime(base.year, base.month, base.day)
    days_ahead = (weekday_idx - base_date.weekday() + 7) % 7
    days_ahead += 7 * (weeks_ahead - 1)
    return base_date + timedelta(days=days_ahead)

def wd_idx(lbl: str) -> int:
    return {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}[lbl]

def pick_duration_select(page):
    """『Hoe lang』のセレクトをラベルに頼らず推測して返す"""
    sels = page.locator("select")
    for i in range(sels.count()):
        txt = sels.nth(i).inner_text()
        # '1 uur', '1,5 uur', '2 uur' などを含むselectを採用
        if re.search(r"\b\d+(?:,\d+)?\s*uur\b", txt, re.I):
            return sels.nth(i)
    return None

def pick_time_select(page):
    """時刻リスト（'15:00 - 16:00' のような option を持つ select）を検出して返す"""
    sels = page.locator("select")
    for i in range(sels.count()):
        txt = sels.nth(i).inner_text()
        if re.search(r"\b\d{2}:\d{2}\b", txt):
            return sels.nth(i)
    return None

def set_date(page, iso_date):
    """input[type=date] を直接操作（change発火含む）"""
    # まず type=date を探す
    inputs = page.locator("input[type='date']")
    if inputs.count() == 0:
        log("date input not found")
        return False
    date_input = inputs.nth(0)
    try:
        # 直接fillするとUIが反応しないことがあるので、evalでchangeイベントも飛ばす
        page.evaluate("""
            (el, val) => { 
                el.value = val; 
                el.dispatchEvent(new Event('input', {bubbles:true})); 
                el.dispatchEvent(new Event('change', {bubbles:true}));
            }
        """, date_input, iso_date)
        return True
    except Exception as e:
        log(f"set_date failed: {e}")
        return False

def main():
    # 計画作成
    today = datetime.now()
    plan = []
    for wlbl, start in TARGETS:
        d = next_weekday(today, wd_idx(wlbl), WEEKS_AHEAD)
        plan.append((d, wlbl, start))

    with sync_playwright() as p:
        # 固まって見えないよう headless=False で動き＆ログ確認しやすく
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(4000)

        log(f"Open: {BOOK_URL}")
        page.goto(BOOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(800)

        # 1) Duration（1,5 uur を選択。無ければ 1 uur）
        dur_sel = pick_duration_select(page)
        if dur_sel:
            txt = dur_sel.inner_text()
            value_to_pick = None
            # value属性ではなく表示テキストベースで選ぶ
            if "1,5 uur" in txt:
                value_to_pick = None  # 後でテキスト一致で拾う
                target_label = "1,5 uur"
            elif "1 uur" in txt:
                target_label = "1 uur"
            else:
                target_label = None

            if target_label:
                opts = dur_sel.locator("option")
                picked = False
                for i in range(opts.count()):
                    lab = opts.nth(i).inner_text().strip()
                    if lab == target_label:
                        val = opts.nth(i).get_attribute("value") or lab
                        try:
                            dur_sel.select_option(val)
                            picked = True
                            log(f"Duration selected: {lab}")
                            break
                        except Exception as e:
                            log(f"Duration select failed: {e}")
                if not picked:
                    log("Duration NOT picked (no matching option)")
        else:
            log("Duration select not found")

        results = []
        # 2) 各日程で date と time を選択して可否判定
        for d, wlbl, start in plan:
            iso = d.strftime("%Y-%m-%d")
            log(f"---- Check {iso} ({wlbl}) {start} ----")

            if not set_date(page, iso):
                results.append((iso, wlbl, start, False, ""))
                continue

            page.wait_for_timeout(500)  # 反映待ち

            time_sel = pick_time_select(page)
            if not time_sel:
                log("time select not found")
                results.append((iso, wlbl, start, False, ""))
                continue

            opts = time_sel.locator("option")
            log(f"time options: {opts.count()}")
            matched = False
            label_text = ""
            for i in range(opts.count()):
                lab = opts.nth(i).inner_text().strip()  # "20:00 - 21:30" 等
                if lab.startswith(start):
                    val = opts.nth(i).get_attribute("value") or lab
                    try:
                        time_sel.select_option(val)
                        matched = True
                        label_text = lab
                        log(f"Matched time: {lab}")
                        break
                    except Exception as e:
                        log(f"time select failed: {e}")
            results.append((iso, wlbl, start, matched, label_text))

        # 結果出力
        for iso, w, st, ok, lab in results:
            print(f"{iso} ({w}) {st} → {'Available ✅' if ok else 'Not available ❌'} {('['+lab+']') if lab else ''}")

        page.wait_for_timeout(800)
        browser.close()

if __name__ == "__main__":
    main()
