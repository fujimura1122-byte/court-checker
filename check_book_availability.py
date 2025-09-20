from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"

# 希望スロット（曜日, 開始時刻）
TARGETS = [
    ("Mon", "20:00"),  # 月 20:00-21:30
    ("Thu", "20:00"),  # 木 20:00-21:30
    ("Sun", "14:00"),  # 日 14:00-15:30
]
DURATION_VALUE = "1,5"  # 「1,5 uur」を選択（inspect結果のvalueに合わせる）

def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int = 2) -> datetime:
    """base から weeks_ahead 週先の特定曜日の日付を返す（weekday_idx: Mon=0..Sun=6）"""
    base_date = datetime(base.year, base.month, base.day)
    # 来週のその曜日
    days_ahead = (weekday_idx - base_date.weekday() + 7) % 7
    days_ahead += 7 * (weeks_ahead - 1)  # “再来週”なら +7
    target = base_date + timedelta(days=days_ahead)
    return target

def label_to_weekday_index(lbl: str) -> int:
    mapping = {"Mon":0, "Tue":1, "Wed":2, "Thu":3, "Fri":4, "Sat":5, "Sun":6}
    return mapping[lbl]

def main():
    today = datetime.now()
    plan = []
    for wd_lbl, start_hhmm in TARGETS:
        d = next_weekday(today, label_to_weekday_index(wd_lbl), weeks_ahead=2)
        plan.append((d, start_hhmm))

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BOOK_URL, wait_until="domcontentloaded")

        # 1) 「Hoe lang wilt u reserveren?」= 1,5 uur を選択
        try:
            page.get_by_label("Hoe lang wilt u reserveren?").select_option(DURATION_VALUE)
        except Exception:
            # ラベルが取れない場合、selectの3番目（inspectで #3 が「Hoe lang」だった）をフォールバック
            sels = page.locator("select")
            sels.nth(2).select_option(DURATION_VALUE)

        # 2) 「Activiteit」は任意。必要なら 'Zaalvoetbal' を選ぶ（無ければスキップ）
        try:
            act_sel = page.get_by_label("Activiteit")
            # 'Zaalvoetbal' があれば選ぶ。無ければ何もしない
            opts = act_sel.locator("option")
            found_zaal = False
            for i in range(opts.count()):
                if "zaalvoetbal" in opts.nth(i).inner_text().lower():
                    val = opts.nth(i).get_attribute("value")
                    act_sel.select_option(val)
                    found_zaal = True
                    break
        except Exception:
            pass

        # 3) 各ターゲット日付で「Voor wanneer?」「Welke tijd」を触って可用性を判定
        for d, start_hhmm in plan:
            # 日付入力：type=date の input になっている想定
            iso_date = d.strftime("%Y-%m-%d")
            ok_date = False
            try:
                date_input = page.get_by_label("Voor wanneer?")
                date_input.fill(iso_date)
                ok_date = True
            except Exception:
                # ラベルが取れない場合は input[type=date] に直接
                try:
                    page.fill("input[type='date']", iso_date)
                    ok_date = True
                except Exception:
                    ok_date = False

            # 時刻セレクトから開始時刻を含む option を探す
            available = False
            chosen_text = None
            if ok_date:
                # 時刻セレクトは「Welke tijd」
                try:
                    time_sel = page.get_by_label("Welke tijd")
                except Exception:
                    # フォールバック：select要素をすべて取得して、表示テキストに ':' を含むものを時刻セレクトとみなす
                    all_selects = page.locator("select")
                    time_sel = None
                    for i in range(all_selects.count()):
                        sample_text = all_selects.nth(i).inner_text()
                        if ":" in sample_text:
                            time_sel = all_selects.nth(i)
                            break

                if time_sel:
                    # option を走査
                    options = time_sel.locator("option")
                    for i in range(options.count()):
                        t = options.nth(i).inner_text().strip()  # 例: "20:00 - 21:00"
                        if t.startswith(start_hhmm):
                            val = options.nth(i).get_attribute("value")
                            # 選択してみる（選べない=disabledなら例外）
                            try:
                                time_sel.select_option(val)
                                available = True
                                chosen_text = t
                                break
                            except Exception:
                                pass

            # 結果を格納
            results.append({
                "date": d.strftime("%Y-%m-%d"),
                "weekday": d.strftime("%a"),
                "start": start_hhmm,
                "available": available,
                "slot_label": chosen_text or "",
            })

        browser.close()

    # 結果表示
    for r in results:
        tag = "Available ✅" if r["available"] else "Not available ❌"
        print(f"{r['date']} ({r['weekday']}) {r['start']} → {tag} {('['+r['slot_label']+']') if r['slot_label'] else ''}")

if __name__ == "__main__":
    main()
