"""
競艇統計分析モジュール - Claude のツールとして呼び出される統計関数群

全ツールはJSON文字列を返す。Claude API Tool Useで自律的に呼び出される。
"""
import json

import numpy as np
import pandas as pd

from .database import query_df


# ── データ取得ヘルパー ────────────────────────────────────────────────────────

def _get_merged() -> pd.DataFrame:
    """race_information + race_results を結合して返す"""
    info = query_df("SELECT * FROM race_information")
    results = query_df("SELECT * FROM race_results")
    if info.empty or results.empty:
        return pd.DataFrame()
    return results.merge(info, on="race_code", how="left")


def _get_payouts() -> pd.DataFrame:
    """payout_results + race_information を結合して返す"""
    info = query_df("SELECT race_code, race_grade, stadium_code, stadium_name FROM race_information")
    payouts = query_df("SELECT * FROM payout_results")
    if info.empty or payouts.empty:
        return pd.DataFrame()
    return payouts.merge(info, on="race_code", how="left")


def _filter(df: pd.DataFrame, grade: str = "All", stadium: str = "All") -> pd.DataFrame:
    """グレード・場でフィルタ"""
    if grade != "All":
        df = df[df["race_grade"] == grade]
    if stadium != "All":
        df = df[(df["stadium_code"] == stadium) | (df["stadium_name"] == stadium)]
    return df


# ── ツール実装 ────────────────────────────────────────────────────────────────

def get_lane_win_rate(stadium: str = "All", grade: str = "All") -> str:
    """
    枠番(1-6)別の勝率・2連対率・3連対率を返す。
    競艇の核心：1号艇（インコース）の圧倒的優位を定量化。

    Parameters
    ----------
    stadium : 場コード(01-24)、場名、または "All"
    grade   : "SG" | "G1" | "G2" | "G3" | "一般" | "All"
    """
    df = _get_merged()
    if df.empty:
        return json.dumps({"error": "データなし"}, ensure_ascii=False)

    df = _filter(df, grade, stadium)
    total_races = df["race_code"].nunique()

    results = []
    for lane in range(1, 7):
        lane_df = df[df["lane"] == lane]
        n = len(lane_df)
        if n == 0:
            continue
        wins = len(lane_df[lane_df["finishing_order"] == 1])
        top2 = len(lane_df[lane_df["finishing_order"] <= 2])
        top3 = len(lane_df[lane_df["finishing_order"] <= 3])
        avg_order = lane_df["finishing_order"].mean()

        results.append({
            "lane": lane,
            "races": n,
            "win_rate": round(wins / n * 100, 1),
            "top2_rate": round(top2 / n * 100, 1),
            "top3_rate": round(top3 / n * 100, 1),
            "avg_finishing_order": round(avg_order, 2),
        })

    return json.dumps({
        "filter": {"stadium": stadium, "grade": grade},
        "total_races": total_races,
        "lane_stats": results,
    }, ensure_ascii=False)


def get_bet_type_roi(bet_type: str = "3連単", grade: str = "All") -> str:
    """
    券種別の平均払戻金・ROI分析。

    Parameters
    ----------
    bet_type : "3連単" | "3連複" | "2連単" | "2連複" | "拡連複" | "単勝" | "複勝"
    grade    : "SG" | "G1" | "G2" | "G3" | "一般" | "All"
    """
    df = _get_payouts()
    if df.empty:
        return json.dumps({"error": "データなし"}, ensure_ascii=False)

    df = _filter(df, grade)
    target = df[df["bet_type"] == bet_type]

    if target.empty:
        return json.dumps({"error": f"{bet_type}のデータなし"}, ensure_ascii=False)

    total_races = target["race_code"].nunique()
    avg_payout = target["payout"].mean()
    median_payout = target["payout"].median()
    max_payout = target["payout"].max()
    min_payout = target["payout"].min()

    return json.dumps({
        "bet_type": bet_type,
        "grade": grade,
        "total_races": total_races,
        "avg_payout": round(avg_payout, 1),
        "median_payout": round(median_payout, 1),
        "max_payout": int(max_payout),
        "min_payout": int(min_payout),
    }, ensure_ascii=False)


def get_popularity_roi(bet_type: str = "単勝") -> str:
    """
    人気順別の的中率・ROI分析。
    どの人気帯が割安/割高かを特定する。

    Parameters
    ----------
    bet_type : "3連単" | "3連複" | "2連単" | "2連複" | "単勝"
    """
    payouts = _get_payouts()
    if payouts.empty:
        return json.dumps({"error": "データなし"}, ensure_ascii=False)

    target = payouts[(payouts["bet_type"] == bet_type) & (payouts["popularity"].notna())]
    if target.empty:
        return json.dumps({"error": f"{bet_type}の人気データなし"}, ensure_ascii=False)

    total_races = target["race_code"].nunique()

    results = []
    for pop, group in target.groupby("popularity"):
        n = len(group)
        avg_payout = group["payout"].mean()
        # ROI = 平均払戻 / 100 * 100 (100円あたり)
        roi = avg_payout / 100 * 100 if bet_type in ("単勝", "複勝") else avg_payout / 100
        results.append({
            "popularity": int(pop),
            "count": n,
            "avg_payout": round(avg_payout, 1),
            "roi_pct": round(roi, 1),
        })

    results.sort(key=lambda x: x["popularity"])
    return json.dumps({
        "bet_type": bet_type,
        "total_races": total_races,
        "popularity_stats": results,
    }, ensure_ascii=False)


def get_odds_pattern_analysis(grade: str = "All") -> str:
    """
    オッズパターン分類分析。
    1号艇オッズでレース構造を「断然/やや優勢/2強/混戦」に分類し、
    各パターンでの枠番別勝率・ROIを返す。
    （horse-raceの核心手法を競艇に移植）

    Parameters
    ----------
    grade : "SG" | "G1" | "G2" | "G3" | "一般" | "All"
    """
    # race_odds から1号艇の単勝オッズを取得
    odds_df = query_df("""
        SELECT race_code, combination, odds
        FROM race_odds
        WHERE bet_type = '単勝'
    """)

    if odds_df.empty:
        return json.dumps({
            "error": "オッズデータなし。先にオッズを収集してください。"
        }, ensure_ascii=False)

    merged = _get_merged()
    if merged.empty:
        return json.dumps({"error": "レースデータなし"}, ensure_ascii=False)

    merged = _filter(merged, grade)

    # 1号艇オッズを結合
    lane1_odds = odds_df[odds_df["combination"] == "1"].rename(columns={"odds": "lane1_odds"})
    merged = merged.merge(lane1_odds[["race_code", "lane1_odds"]], on="race_code", how="inner")

    if merged.empty:
        return json.dumps({"error": "オッズとレース結果の紐付けデータなし"}, ensure_ascii=False)

    # パターン分類
    def classify(odds):
        if odds <= 1.5:
            return "A:断然"
        elif odds <= 2.5:
            return "B:やや優勢"
        elif odds <= 4.0:
            return "C:拮抗"
        else:
            return "D:混戦"

    merged["pattern"] = merged["lane1_odds"].apply(classify)

    results = []
    for pattern, group in merged.groupby("pattern"):
        race_codes = group["race_code"].unique()
        n_races = len(race_codes)

        # 1号艇の成績
        lane1 = group[group["lane"] == 1]
        lane1_wins = len(lane1[lane1["finishing_order"] == 1])
        lane1_win_rate = round(lane1_wins / len(lane1) * 100, 1) if len(lane1) > 0 else 0

        # 各枠の勝率
        lane_wins = {}
        for lane in range(1, 7):
            l = group[group["lane"] == lane]
            w = len(l[l["finishing_order"] == 1])
            lane_wins[lane] = round(w / len(l) * 100, 1) if len(l) > 0 else 0

        results.append({
            "pattern": pattern,
            "races": n_races,
            "avg_lane1_odds": round(group.drop_duplicates("race_code")["lane1_odds"].mean(), 2),
            "lane1_win_rate": lane1_win_rate,
            "lane_win_rates": lane_wins,
        })

    results.sort(key=lambda x: x["pattern"])
    return json.dumps({
        "grade": grade,
        "total_races": merged["race_code"].nunique(),
        "patterns": results,
    }, ensure_ascii=False)


def get_start_timing_analysis(stadium: str = "All") -> str:
    """
    STタイミングと着順の相関分析。
    スタートの速さが勝率にどう影響するか。

    Parameters
    ----------
    stadium : 場コード(01-24)、場名、または "All"
    """
    df = _get_merged()
    if df.empty:
        return json.dumps({"error": "データなし"}, ensure_ascii=False)

    df = _filter(df, stadium=stadium)
    df = df[df["start_timing"].notna()]

    if df.empty:
        return json.dumps({"error": "STデータなし"}, ensure_ascii=False)

    # STタイミングを区間に分割
    bins = [0, 0.10, 0.15, 0.20, 0.25, 0.30, 1.0]
    labels = ["~0.10", "0.10-0.15", "0.15-0.20", "0.20-0.25", "0.25-0.30", "0.30~"]
    df["st_bin"] = pd.cut(df["start_timing"], bins=bins, labels=labels, right=False)

    results = []
    for st_bin, group in df.groupby("st_bin", observed=True):
        n = len(group)
        if n == 0:
            continue
        wins = len(group[group["finishing_order"] == 1])
        top3 = len(group[group["finishing_order"] <= 3])
        avg_order = group["finishing_order"].mean()

        results.append({
            "st_range": str(st_bin),
            "count": n,
            "win_rate": round(wins / n * 100, 1),
            "top3_rate": round(top3 / n * 100, 1),
            "avg_finishing_order": round(avg_order, 2),
        })

    return json.dumps({
        "stadium": stadium,
        "total_entries": len(df),
        "st_stats": results,
    }, ensure_ascii=False)


def get_stadium_summary() -> str:
    """
    場別のレース数・1号艇勝率・平均払戻金のサマリー。
    場ごとの特性（イン有利度など）を比較する。
    """
    df = _get_merged()
    if df.empty:
        return json.dumps({"error": "データなし"}, ensure_ascii=False)

    results = []
    for (code, name), group in df.groupby(["stadium_code", "stadium_name"]):
        n_races = group["race_code"].nunique()
        lane1 = group[group["lane"] == 1]
        lane1_wins = len(lane1[lane1["finishing_order"] == 1])
        lane1_rate = round(lane1_wins / len(lane1) * 100, 1) if len(lane1) > 0 else 0

        results.append({
            "stadium_code": code,
            "stadium_name": name,
            "total_races": n_races,
            "lane1_win_rate": lane1_rate,
        })

    results.sort(key=lambda x: x["lane1_win_rate"], reverse=True)
    return json.dumps({
        "total_stadiums": len(results),
        "stadiums": results,
    }, ensure_ascii=False)


# ── Claude Tool Use 定義 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_lane_win_rate",
        "description": "枠番(1-6)別の勝率・2連対率・3連対率を返す。競艇の核心：1号艇（イン）の優位を定量化。",
        "input_schema": {
            "type": "object",
            "properties": {
                "stadium": {"type": "string", "description": "場コード(01-24)、場名、または'All'", "default": "All"},
                "grade": {"type": "string", "enum": ["SG", "G1", "G2", "G3", "一般", "All"], "default": "All"},
            },
        },
    },
    {
        "name": "get_bet_type_roi",
        "description": "券種別の平均払戻金・ROI分析。",
        "input_schema": {
            "type": "object",
            "properties": {
                "bet_type": {"type": "string", "enum": ["3連単", "3連複", "2連単", "2連複", "拡連複", "単勝", "複勝"], "default": "3連単"},
                "grade": {"type": "string", "enum": ["SG", "G1", "G2", "G3", "一般", "All"], "default": "All"},
            },
        },
    },
    {
        "name": "get_popularity_roi",
        "description": "人気順別の的中率・ROI分析。どの人気帯が割安/割高か。",
        "input_schema": {
            "type": "object",
            "properties": {
                "bet_type": {"type": "string", "enum": ["3連単", "3連複", "2連単", "2連複", "単勝"], "default": "単勝"},
            },
        },
    },
    {
        "name": "get_odds_pattern_analysis",
        "description": "1号艇オッズでレース構造を分類（断然/優勢/拮抗/混戦）し、各パターンの枠番別勝率を返す。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "string", "enum": ["SG", "G1", "G2", "G3", "一般", "All"], "default": "All"},
            },
        },
    },
    {
        "name": "get_start_timing_analysis",
        "description": "STタイミングと着順の相関分析。スタートの速さが勝率にどう影響するか。",
        "input_schema": {
            "type": "object",
            "properties": {
                "stadium": {"type": "string", "description": "場コード(01-24)、場名、または'All'", "default": "All"},
            },
        },
    },
    {
        "name": "get_stadium_summary",
        "description": "場別のレース数・1号艇勝率サマリー。場ごとの特性（イン有利度）を比較。",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_FUNCTIONS = {
    "get_lane_win_rate": get_lane_win_rate,
    "get_bet_type_roi": get_bet_type_roi,
    "get_popularity_roi": get_popularity_roi,
    "get_odds_pattern_analysis": get_odds_pattern_analysis,
    "get_start_timing_analysis": get_start_timing_analysis,
    "get_stadium_summary": get_stadium_summary,
}
