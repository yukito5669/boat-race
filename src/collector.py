"""
BOATRACE公式サイト スクレイピングモジュール

対象: https://www.boatrace.jp/
- レース結果 (raceresult)
- 出走表 (racelist) → 選手ランク・モーター・ボート情報
- 払戻金 (raceresult内)
- スタート情報 (raceresult内)
"""
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from src.database import (
    STADIUM_MAP,
    insert_payout_results,
    insert_race_information,
    insert_race_odds,
    insert_race_results,
    race_exists,
    race_odds_exists,
    update_racelist_for_race,
)

BASE_URL = "https://www.boatrace.jp/owpc/pc/race"
REQUEST_DELAY = 1.5  # 秒
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _fetch(url: str) -> BeautifulSoup | None:
    """URLからHTMLを取得してBeautifulSoupを返す"""
    time.sleep(REQUEST_DELAY)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [ERROR] {url}: {e}")
        return None


# ── レース結果ページ解析 ────────────────────────────────────────────────────

def _parse_race_result(soup: BeautifulSoup) -> list[dict]:
    """着順テーブルを解析"""
    results = []
    # 着順テーブル: table.is-w495 の最初のテーブル
    tables = soup.select("div.grid_unit .table1 table.is-w495")
    if not tables:
        return results

    result_table = tables[0]
    for tbody in result_table.find_all("tbody"):
        tr = tbody.find("tr")
        if not tr:
            continue
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        # 着順: 全角数字 → int
        order_text = tds[0].get_text(strip=True)
        try:
            finishing_order = int(order_text.translate(
                str.maketrans("１２３４５６７８９０", "1234567890")
            ))
        except ValueError:
            finishing_order = 99  # 転覆・失格等

        # 枠番
        lane_text = tds[1].get_text(strip=True)
        try:
            lane = int(lane_text)
        except ValueError:
            lane = 0

        # 選手ID・選手名
        racer_id_span = tds[2].find("span", class_="is-fs12")
        racer_id = racer_id_span.get_text(strip=True) if racer_id_span else ""

        racer_name_span = tds[2].find("span", class_=re.compile(r"is-fs18"))
        racer_name = racer_name_span.get_text(strip=True) if racer_name_span else ""
        # 全角スペースを正規化
        racer_name = re.sub(r"\s+", "", racer_name)

        # レースタイム
        race_time = tds[3].get_text(strip=True)

        results.append({
            "finishing_order": finishing_order,
            "lane": lane,
            "racer_id": racer_id,
            "racer_name": racer_name,
            "race_time": race_time if race_time else None,
        })

    return results


def _parse_start_info(soup: BeautifulSoup) -> dict[int, float]:
    """スタート情報を解析。枠番 → STタイミング(秒)のdict"""
    st_map = {}
    start_divs = soup.select("div.table1_boatImage1")
    for div in start_divs:
        # 枠番
        num_span = div.find("span", class_=re.compile(r"table1_boatImage1Number"))
        if not num_span:
            continue
        try:
            lane = int(num_span.get_text(strip=True))
        except ValueError:
            continue

        # STタイミング
        time_span = div.find("span", class_="table1_boatImage1TimeInner")
        if time_span:
            time_text = time_span.get_text(strip=True).split()[0]  # ".27 逃げ" → ".27"
            try:
                st_map[lane] = float(time_text)
            except ValueError:
                pass

    return st_map


def _parse_payouts(soup: BeautifulSoup) -> list[dict]:
    """払戻金テーブルを解析"""
    payouts = []
    # 「勝式」ヘッダーを持つテーブルを探す
    payout_table = None
    for table in soup.select("div.table1 table"):
        th = table.find("th", string=re.compile("勝式"))
        if th:
            payout_table = table
            break
    if not payout_table:
        return payouts

    current_bet_type = None
    for tbody in payout_table.find_all("tbody"):
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue

            # 勝式（rowspanがある行で更新）
            offset = 0
            if tds[0].get("rowspan"):
                current_bet_type = tds[0].get_text(strip=True)
                offset = 1
            elif len(tds) >= 3 and not tds[0].get("rowspan"):
                # bet_typeが前行からの継続
                pass

            if not current_bet_type:
                continue

            # 組番
            combo_td = tds[offset] if offset < len(tds) else None
            if not combo_td:
                continue

            numbers = combo_td.select("span.numberSet1_number")
            if not numbers:
                continue

            combo_nums = [n.get_text(strip=True) for n in numbers]
            separators = combo_td.select("span.numberSet1_text")
            sep = separators[0].get_text(strip=True) if separators else "-"
            combination = sep.join(combo_nums)

            # 払戻金
            payout_td = tds[offset + 1] if offset + 1 < len(tds) else None
            if not payout_td:
                continue
            payout_text = payout_td.get_text(strip=True)
            payout_text = payout_text.replace("¥", "").replace(",", "").replace("￥", "")
            if not payout_text or payout_text == "\xa0":
                continue
            try:
                payout = int(payout_text)
            except ValueError:
                continue

            # 人気
            pop_td = tds[offset + 2] if offset + 2 < len(tds) else None
            popularity = None
            if pop_td:
                pop_text = pop_td.get_text(strip=True)
                try:
                    popularity = int(pop_text)
                except ValueError:
                    pass

            payouts.append({
                "bet_type": current_bet_type,
                "combination": combination,
                "payout": payout,
                "popularity": popularity,
            })

    return payouts


def _parse_race_grade(soup: BeautifulSoup) -> str:
    """レースグレードを判定"""
    heading = soup.find("div", class_="heading2_title")
    if not heading:
        return "一般"

    classes = heading.get("class", [])
    class_str = " ".join(classes)

    if "is-sg" in class_str:
        return "SG"
    elif "is-g1" in class_str:
        return "G1"
    elif "is-g2" in class_str:
        return "G2"
    elif "is-g3" in class_str:
        return "G3"
    return "一般"


def _parse_race_name(soup: BeautifulSoup) -> str:
    """レース名（開催タイトル）を取得"""
    h2 = soup.find("h2", class_="heading2_titleName")
    return h2.get_text(strip=True) if h2 else ""


# ── 出走表ページ解析（選手ランク・モーター・ボート） ─────────────────────────

_FW_DIGITS = str.maketrans("１２３４５６", "123456")


def _parse_racelist(soup: BeautifulSoup) -> dict[int, dict]:
    """出走表ページから lane → 各種情報 のdictを返す。

    Returns: {lane: {
        "racer_id": str, "racer_rank": "A1"|...,
        "motor_no": int, "motor_top2_rate": float, "motor_top3_rate": float,
        "boat_no": int,  "boat_top2_rate": float,  "boat_top3_rate": float,
    }}
    """
    out: dict[int, dict] = {}
    tables = soup.select("table")
    if len(tables) < 2:
        return out

    # 主要テーブルを特定: tbody が 6 個ある最初のテーブル（6艇分）
    target = None
    for t in tables:
        if len(t.find_all("tbody")) == 6:
            target = t
            break
    if target is None:
        return out

    for tbody in target.find_all("tbody"):
        rows = tbody.find_all("tr")
        if not rows:
            continue
        cells = rows[0].find_all("td")
        if len(cells) < 8:
            continue

        # 枠番（全角）
        lane_text = cells[0].get_text(strip=True).translate(_FW_DIGITS)
        try:
            lane = int(lane_text)
        except ValueError:
            continue
        if lane < 1 or lane > 6:
            continue

        # 選手ID + ランク
        racer_block = cells[2].get_text(" ", strip=True)
        m = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)", racer_block)
        racer_id = m.group(1) if m else None
        racer_rank = m.group(2) if m else None

        # モーター: '16 48.60 65.42'
        motor_parts = cells[6].get_text(" ", strip=True).split()
        motor_no = int(motor_parts[0]) if len(motor_parts) >= 1 and motor_parts[0].isdigit() else None
        motor_t2 = float(motor_parts[1]) if len(motor_parts) >= 2 else None
        motor_t3 = float(motor_parts[2]) if len(motor_parts) >= 3 else None

        # ボート: '37 23.08 46.15'
        boat_parts = cells[7].get_text(" ", strip=True).split()
        boat_no = int(boat_parts[0]) if len(boat_parts) >= 1 and boat_parts[0].isdigit() else None
        boat_t2 = float(boat_parts[1]) if len(boat_parts) >= 2 else None
        boat_t3 = float(boat_parts[2]) if len(boat_parts) >= 3 else None

        out[lane] = {
            "racer_id": racer_id,
            "racer_rank": racer_rank,
            "motor_no": motor_no,
            "motor_top2_rate": motor_t2,
            "motor_top3_rate": motor_t3,
            "boat_no": boat_no,
            "boat_top2_rate": boat_t2,
            "boat_top3_rate": boat_t3,
        }

    return out


def _fetch_racelist_info(hd: str, jcd: str, rno: int) -> dict[int, dict]:
    """出走表ページを取得して `_parse_racelist` の結果を返す"""
    url = f"{BASE_URL}/racelist?rno={rno}&jcd={jcd}&hd={hd}"
    soup = _fetch(url)
    if not soup:
        return {}
    return _parse_racelist(soup)


# ── 3連単オッズページ解析 ───────────────────────────────────────────────────

def _build_3t_combinations() -> list[str]:
    """3連単120通りを、BOATRACE公式のodds3tテーブル DOM出現順に返す。

    DOM順:
      5ブロック(2着バリアント) × 4行(3着バリアント) × 6列(1着=1..6)
    各列cにおいて 2着 = sorted([1..6]\\{c})[block],
    3着 = sorted([1..6]\\{c,s})[row_in_block]
    """
    combos = []
    for block in range(5):
        for row_in_block in range(4):
            for col in range(6):
                first = col + 1
                second_choices = [x for x in range(1, 7) if x != first]
                second = second_choices[block]
                third_choices = [x for x in range(1, 7) if x != first and x != second]
                third = third_choices[row_in_block]
                combos.append(f"{first}-{second}-{third}")
    return combos


_3T_COMBINATIONS = _build_3t_combinations()


def _parse_3t_odds(soup: BeautifulSoup) -> list[dict]:
    """3連単オッズテーブルから120通りの (combination, odds) を抽出"""
    cells = soup.select("td.oddsPoint")
    if len(cells) != 120:
        # レース未実施・中止・データ欠損など
        return []

    odds = []
    for combo, cell in zip(_3T_COMBINATIONS, cells):
        txt = cell.get_text(strip=True)
        try:
            value = float(txt)
        except ValueError:
            continue  # 「欠場」等は数値変換不可でスキップ
        odds.append({
            "bet_type": "3連単",
            "combination": combo,
            "odds": value,
        })
    return odds


def collect_race_odds(hd: str, jcd: str, rno: int, force: bool = False) -> bool:
    """1レースの3連単確定オッズを収集。race_oddsに既存データがあればスキップ。"""
    race_code = f"{hd}_{jcd}_{rno:02d}"
    if not force and race_odds_exists(race_code):
        return False

    url = f"{BASE_URL}/odds3t?rno={rno}&jcd={jcd}&hd={hd}"
    soup = _fetch(url)
    if not soup:
        return False

    odds = _parse_3t_odds(soup)
    if not odds:
        return False

    insert_race_odds(race_code, odds)
    return True


# ── 公開API: 1レース収集 ───────────────────────────────────────────────────

def _save_race_from_soup(
    soup: BeautifulSoup, hd: str, jcd: str, rno: int
) -> bool:
    """パース済みsoupからレースデータをDB保存する内部関数"""
    race_code = f"{hd}_{jcd}_{rno:02d}"

    results = _parse_race_result(soup)
    if not results:
        return False

    st_map = _parse_start_info(soup)
    racelist = _fetch_racelist_info(hd, jcd, rno)  # lane -> {rank, motor_no, ...}
    for r in results:
        lane = r["lane"]
        r["start_timing"] = st_map.get(lane)
        r["course"] = lane
        rl = racelist.get(lane, {})
        r["racer_rank"] = rl.get("racer_rank")
        r["motor_no"] = rl.get("motor_no")
        r["motor_top2_rate"] = rl.get("motor_top2_rate")
        r["motor_top3_rate"] = rl.get("motor_top3_rate")
        r["boat_no"] = rl.get("boat_no")
        r["boat_top2_rate"] = rl.get("boat_top2_rate")
        r["boat_top3_rate"] = rl.get("boat_top3_rate")

    stadium_name = STADIUM_MAP.get(jcd, "不明")
    race_date = f"{hd[:4]}-{hd[4:6]}-{hd[6:8]}"

    race_info = {
        "race_code": race_code,
        "race_date": race_date,
        "stadium_code": jcd,
        "stadium_name": stadium_name,
        "race_number": rno,
        "race_grade": _parse_race_grade(soup),
        "race_name": _parse_race_name(soup),
        "year": int(hd[:4]),
    }

    payouts = _parse_payouts(soup)

    insert_race_information(race_info)
    insert_race_results(race_code, results)
    if payouts:
        insert_payout_results(race_code, payouts)

    # 3連単確定オッズを追加取得（結果が保存できたレースのみ）
    odds_ok = collect_race_odds(hd, jcd, rno)
    odds_note = "+オッズ" if odds_ok else ""

    print(f"  [OK] {race_code} ({stadium_name} {rno}R): {len(results)}艇, {len(payouts)}件払戻{odds_note}")
    return True


def collect_race(hd: str, jcd: str, rno: int, force: bool = False) -> bool:
    """1レースのデータを収集してDBに保存

    Args:
        hd: 日付 (YYYYMMDD)
        jcd: 場コード (01-24)
        rno: レース番号 (1-12)
        force: 既存データがあっても再取得

    Returns: 保存成功したらTrue
    """
    race_code = f"{hd}_{jcd}_{rno:02d}"

    if not force and race_exists(race_code):
        return False

    url = f"{BASE_URL}/raceresult?rno={rno}&jcd={jcd}&hd={hd}"
    soup = _fetch(url)
    if not soup:
        return False

    return _save_race_from_soup(soup, hd, jcd, rno)


# ── 公開API: 日単位収集 ────────────────────────────────────────────────────

def collect_date(hd: str, stadium_codes: list[str] | None = None, force: bool = False) -> int:
    """指定日のレースを収集

    Args:
        hd: 日付 (YYYYMMDD)
        stadium_codes: 対象場コードリスト (Noneなら全24場)
        force: 既存データがあっても再取得

    Returns: 収集レース数
    """
    targets = stadium_codes or list(STADIUM_MAP.keys())
    total = 0

    for jcd in targets:
        stadium_name = STADIUM_MAP.get(jcd, jcd)

        # 1Rで開催有無を確認
        url = f"{BASE_URL}/raceresult?rno=1&jcd={jcd}&hd={hd}"
        soup = _fetch(url)
        if not soup or not _parse_race_result(soup):
            continue

        print(f"\n[{hd}] {stadium_name} ({jcd}):")

        # 1Rは既にsoupがあるので直接保存
        race_code_1r = f"{hd}_{jcd}_01"
        if force or not race_exists(race_code_1r):
            if _save_race_from_soup(soup, hd, jcd, 1):
                total += 1

        # 2R-12R
        for rno in range(2, 13):
            if collect_race(hd, jcd, rno, force=force):
                total += 1

    print(f"\n[完了] {hd}: {total}レース収集")
    return total


# ── 公開API: 既存レースのオッズのみ後追い収集 ───────────────────────────────

def collect_missing_odds(limit: int | None = None) -> tuple[int, int]:
    """race_oddsが未収集のレースに対して3連単オッズを取得する。

    BOATRACE公式はオッズを約20-30日分しか保持しないため、期限切れレースもあり得る。
    404・データなしはスキップして継続する。

    Args:
        limit: 処理する最大レース数（None=全件）

    Returns: (成功数, スキップ数)
    """
    from src.database import query_df

    df = query_df(
        """
        SELECT ri.race_code, ri.race_date, ri.stadium_code, ri.stadium_name, ri.race_number
        FROM race_information ri
        LEFT JOIN (
            SELECT DISTINCT race_code FROM race_odds
        ) ro ON ro.race_code = ri.race_code
        WHERE ro.race_code IS NULL
        ORDER BY ri.race_date DESC, ri.stadium_code, ri.race_number
        """
    )
    if df.empty:
        print("[オッズ後追い] 対象レースなし")
        return 0, 0

    if limit:
        df = df.head(limit)

    total = len(df)
    success, skipped = 0, 0
    print(f"[オッズ後追い] 対象: {total} レース")

    current_date = None
    for idx, row in df.iterrows():
        hd = row["race_date"].replace("-", "")
        jcd = row["stadium_code"]
        rno = int(row["race_number"])

        if row["race_date"] != current_date:
            current_date = row["race_date"]
            print(f"\n[{current_date}]", flush=True)

        # 一過性のネットワーク/DNS/Connection reset 等を fetch+書き込みの双方で最大3回リトライ。
        # collect_race_odds は内部で fetch と insert_race_odds (batch) の両方を行うため、関数全体を覆う。
        ok = False
        last_exc = None
        for attempt in range(3):
            try:
                ok = collect_race_odds(hd, jcd, rno)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                wait = 5 * (attempt + 1)
                print(f"  [retry {attempt+1}/3] {row['race_code']}: {type(e).__name__} -> {wait}s sleep", flush=True)
                time.sleep(wait)

        if last_exc is not None:
            skipped += 1
            print(f"  [error] {row['race_code']} ({row['stadium_name']} {rno}R): {type(last_exc).__name__}", flush=True)
            continue

        if ok:
            success += 1
            print(f"  [OK]   {row['race_code']} ({row['stadium_name']} {rno}R)", flush=True)
        else:
            skipped += 1
            print(f"  [skip] {row['race_code']} ({row['stadium_name']} {rno}R): オッズなし/期限切れ", flush=True)

    print(f"\n[完了] 成功: {success}, スキップ: {skipped}", flush=True)
    return success, skipped


# ── 公開API: 既存レースのracelist情報を後追い更新 ───────────────────────────

def collect_missing_racelist(
    limit: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[int, int]:
    """racer_rank または motor_no が NULL のレースに対して racelist 情報を後追い取得しUPDATE。

    Args:
        limit: 処理する最大レース数（None=全件）
        start_date: 対象日付の下限 (YYYY-MM-DD inclusive)
        end_date:   対象日付の上限 (YYYY-MM-DD inclusive)

    Returns: (成功数, スキップ数)
    """
    from src.database import query_df

    where_parts = [
        """race_code IN (
            SELECT race_code FROM race_results
            WHERE racer_rank IS NULL OR motor_no IS NULL
            GROUP BY race_code
        )"""
    ]
    params: list = []
    if start_date:
        where_parts.append("race_date >= ?")
        params.append(start_date)
    if end_date:
        where_parts.append("race_date <= ?")
        params.append(end_date)
    where_clause = " AND ".join(where_parts)

    df = query_df(
        f"""
        SELECT race_code, race_date, stadium_code, stadium_name, race_number
        FROM race_information
        WHERE {where_clause}
        ORDER BY race_date DESC, stadium_code, race_number
        """,
        params,
    )
    if df.empty:
        print("[racelist後追い] 対象レースなし", flush=True)
        return 0, 0

    if limit:
        df = df.head(limit)

    total = len(df)
    success, skipped = 0, 0
    print(f"[racelist後追い] 対象: {total} レース", flush=True)

    current_date = None
    for _, row in df.iterrows():
        hd = row["race_date"].replace("-", "")
        jcd = row["stadium_code"]
        rno = int(row["race_number"])
        race_code = row["race_code"]

        if row["race_date"] != current_date:
            current_date = row["race_date"]
            print(f"\n[{current_date}]", flush=True)

        # ネットワーク/DNS/Connection reset 等の一過性エラーは fetch / DB-update の双方で最大3回リトライ。
        # 全失敗ならそのレースだけスキップして次へ進む（全体停止を防ぐ）。
        def _do_with_retry(label: str, fn):
            last = None
            for attempt in range(3):
                try:
                    return fn(), None
                except Exception as e:
                    last = e
                    wait = 5 * (attempt + 1)
                    print(f"  [retry {attempt+1}/3] {race_code} {label}: {type(e).__name__} -> {wait}s sleep", flush=True)
                    time.sleep(wait)
            return None, last

        info, fetch_exc = _do_with_retry("fetch", lambda: _fetch_racelist_info(hd, jcd, rno))
        if fetch_exc is not None or not info:
            skipped += 1
            label = type(fetch_exc).__name__ if fetch_exc else "no-data"
            print(f"  [skip] {race_code} ({row['stadium_name']} {rno}R): {label}", flush=True)
            continue

        n, upd_exc = _do_with_retry("update", lambda: update_racelist_for_race(race_code, info))
        if upd_exc is not None:
            skipped += 1
            print(f"  [error] {race_code} ({row['stadium_name']} {rno}R): UPDATE {type(upd_exc).__name__}", flush=True)
            continue

        if n and n > 0:
            success += 1
            print(f"  [OK]   {race_code} ({row['stadium_name']} {rno}R): {n} 艇更新", flush=True)
        else:
            skipped += 1
            print(f"  [skip] {race_code} ({row['stadium_name']} {rno}R): UPDATE 0行", flush=True)

    print(f"\n[完了] 成功: {success}, スキップ: {skipped}", flush=True)
    return success, skipped


# ── 公開API: 期間収集 ──────────────────────────────────────────────────────

def collect_date_range(
    start_date: str,
    end_date: str,
    stadium_codes: list[str] | None = None,
    force: bool = False,
) -> int:
    """期間のレースを収集

    Args:
        start_date: 開始日 (YYYY-MM-DD)
        end_date: 終了日 (YYYY-MM-DD)
        stadium_codes: 対象場コードリスト
        force: 既存データがあっても再取得

    Returns: 総収集レース数
    """
    from datetime import timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total = 0

    current = start
    while current <= end:
        hd = current.strftime("%Y%m%d")
        print(f"\n{'='*60}")
        print(f"  {current.strftime('%Y-%m-%d')}")
        print(f"{'='*60}")
        total += collect_date(hd, stadium_codes=stadium_codes, force=force)
        current += timedelta(days=1)

    print(f"\n[総計] {start_date} ~ {end_date}: {total}レース収集")
    return total
