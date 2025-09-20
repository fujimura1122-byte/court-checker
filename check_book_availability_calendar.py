from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import re

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"

# 再来週の固定スロット
TARGETS = [("Mon","20:00"), ("Thu","20:00"), ("Sun","14:00")]
WEEKS_AHEAD = 2

MONTH_MAP = {1:"jan",2:"feb",3:"mrt",4:"apr",5:"mei",6:"jun",7:"jul",8:"aug",9:"sep",10:"okt",11:"nov",12:"dec"}

def wd_idx(lbl): return {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}[lbl]
def next_weekday(base, idx, weeks_ahead=2):
    base = datetime(base.year, base.month, base.day)
    days = (idx - base.weekday() + 7) % 7
    days += 7*(weeks_ahead-1)
    return base + timedelta(days=days)

def log(msg): print("[LOG]", msg, flush=True)

def select_option_by_text(sel, text_exact):
    """optionの表示テキスト一致で選択（valueが変でもOK）"""
    opts = sel.locator("option")
    for i in range(opts.count()):
        t = opts.nth(i).inner_text().strip()
        if t == text_exact:
            val = opts.nth(i).get_attribute("value") or t
            sel.select_option(val)
            return True
    return False

def main():
    today = datetime.now()
    plan = [(next_weekday(today, wd_idx(w), WEEKS_AHEAD), w, hh) for (w, hh) in TARGETS]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 見える方が安心
        page = browser.new_page()
        page.set_default_timeout(4000)

        log("open page")
        page.goto(BOOK_URL, wait_until="domcontentloaded")

        # 1) 1,5 uur に設定（無ければ 1 uur）
        dur_sel = page.locator("select").filter(has_text=re.compile(r"\b1,5 uur\b|\b1 uur\b", re.I)).first
        if dur_sel.count() == 0:
            # 予備：ラベルから
            try:
                dur_sel = page.get_by_label("Hoe lang wilt u reserveren?")
            except:
                pass
        if dur_sel and dur_sel.count():
            txt = dur_sel.inner_text()
            pick = "1,5 uur" if "1,5 uur" in txt else "1 uur"
            if not select_option_by_text(dur_sel, pick):
                log("duration pick failed")
            else:
                log(f"duration = {pick}")
        else:
            log("duration select not found")

        # 2) 年・月セレクト (#9 年, #8 月) を特定
        selects = page.locator("select")
        year_sel = None; month_sel = None
        for i in range(selects.count()):
            inner = selects.nth(i).inner_text().lower()
            if re.search(r"\b20\d{2}\b", inner) and selects.nth(i).locator("option").count() >= 5:
                year_sel = selects.nth(i)
            if any(m in inner for m in ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]):
                month_sel = selects.nth(i)

        if not (year_sel and month_sel):
            log("year/month select not found"); browser.close(); return

        results = []
        for d, wlbl, start_hhmm in plan:
            log(f"check {d.strftime('%Y-%m-%d')} ({wlbl}) {start_hhmm}")

            # 年と月を合わせる
            try:
                year_sel.select_option(str(d.year))
            except:
                pass
            mon_abbr = MONTH_MAP[d.month]  # 'sep','okt' など
            # 月はvalueが数字でも略称でも対応
            picked_month = False
            opts = month_sel.locator("option")
            for i in range(opts.count()):
                t = opts.nth(i).inner_text().strip().lower()
                v = (opts.nth(i).get_attribute("value") or "").lower()
                if mon_abbr in (t, v):
                    month_sel.select_option(opts.nth(i).get_attribute("value") or t)
                    picked_month = True
                    break
            if not picked_month:
                # valueが数字（'8','9'など）の場合
                try:
                    month_sel.select_option(str(d.month-1))  # 0始まりの可能性
                except:
                    try:
                        month_sel.select_option(str(d.month))
                    except:
                        pass

            page.wait_for_timeout(400)

            # 3) カレンダーから「日」をクリック
            # ボタンに日数字だけが表示される要素を探してクリック
            day_str = str(d.day)
            # よくある実装：日セルは button/td 内のテキストが日付
            clicked = False
            # まず role=button で数字一致
            buttons = page.locator("button").filter(has_text=day_str)
            for i in range(min(buttons.count(), 40)):
                txt = buttons.nth(i).inner_text().strip()
                if txt == day_str:
                    try:
                        buttons.nth(i).click()
                        clicked = True
                        break
                    except:
                        pass
            if not clicked:
                # table内のクリック（td/divなど）
                cells = page.locator("td,div").filter(has_text=day_str)
                for i in range(min(cells.count(), 200)):
                    txt = cells.nth(i).inner_text().strip()
                    if txt == day_str:
                        try:
                            cells.nth(i).click()
                            clicked = True
                            break
                        except:
                            pass

            # 4) 時間セレクトから開始時刻を探す
            available = False; label_text = ""
            time_sel = None
            try:
                time_sel = page.get_by_label("Welke tijd")
            except:
                # テキストに ':' を含むselect
                for i in range(selects.count()):
                    if ":" in selects.nth(i).inner_text():
                        time_sel = selects.nth(i); break

            if time_sel:
                opts = time_sel.locator("option")
                for i in range(opts.count()):
                    t = opts.nth(i).inner_text().strip()  # "20:00 - 21:30" など
                    if t.startswith(start_hhmm):
                        try:
                            time_sel.select_option(opts.nth(i).get_attribute("value") or t)
                            available = True; label_text = t
                            break
                        except:
                            pass

            results.append((d.strftime("%Y-%m-%d"), wlbl, start_hhmm, available, label_text))

        # 結果出力
        for date_str, wlbl, hhmm, ok, lab in results:
            print(f"{date_str} ({wlbl}) {hhmm} → {'Available ✅' if ok else 'Not available ❌'} {('['+lab+']') if lab else ''}")

        page.wait_for_timeout(600)
        browser.close()

if __name__ == "__main__":
    main()
