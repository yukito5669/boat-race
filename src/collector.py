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
    insert_race_results,
    race_exists,
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

def _fetch_racelist_info(hd: str, jcd: str, rno: int) -> dict[str, dict]:
    """出走表ページから選手ランク・モーター・ボート番号を取得

    Returns: {racer_id: {"racer_rank": "A1", "motor_no": 38, "boat_no": 15}}
    """
    url = f"{BASE_URL}/racelist?rno={rno}&jcd={jcd}&hd={hd}"
    soup = _fetch(url)
    if not soup:
        return {}

    info = {}
    # 出走表の各選手行
    tbody_list = soup.select("div.table1 tbody.is-fs12")
    if not tbody_list:
        tbody_list = soup.select("table.is-w748 tbody, table.is-w1200 tbody")

    for tbody in tbody_list:
        tds = tbody.select("td")
        if len(tds) < 3:
            continue

        # 選手ID / ランク を探す
        for td in tds:
            text = td.get_text(strip=True)
            # "5316/B1" パターン
            m = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)", text)
            if m:
                racer_id = m.group(1)
                racer_rank = m.group(2)
                info[racer_id] = {"racer_rank": racer_rank, "motor_no": None, "boat_no": None}
                break

    # モーター・ボート番号はテーブル構造に依存するため、別途パース
    # 出走表テーブルの全行を走査
    all_tables = soup.select("div.table1 table")
    for table in all_tables:
        rows = table.select("tbody")
        for row in rows:
            all_tds = row.select("td")
            full_text = " ".join(td.get_text(strip=True) for td in all_tds)

            # 選手IDを特定
            id_match = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)", full_text)
            if not id_match:
                continue
            racer_id = id_match.group(1)
            if racer_id not in info:
                info[racer_id] = {"racer_rank": id_match.group(2), "motor_no": None, "boat_no": None}

            # モーター・ボート番号をテキストから抽出
            for td in all_tds:
                td_text = td.get_text(strip=True)
                # モーター番号の候補（2-3桁の数字で、他のフィールドでない）
                # 出走表の構造に基づいて位置で判別する方がよい

    return info


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
    for r in results:
        r["start_timing"] = st_map.get(r["lane"])
        r["course"] = r["lane"]
        r["racer_rank"] = None
        r["motor_no"] = None
        r["boat_no"] = None

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

    print(f"  [OK] {race_code} ({stadium_name} {rno}R): {len(results)}艇, {len(payouts)}件払戻")
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
