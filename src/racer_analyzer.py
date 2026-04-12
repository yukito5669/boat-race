"""
選手別分析モジュール - Claude のツールとして呼び出される選手分析関数群

全ツールはJSON文字列を返す。Claude API Tool Useで自律的に呼び出される。
"""
import json

import pandas as pd

from .database import query_df


def get_racer_profile(racer_id: str) -> str:
    """
    選手プロファイル（通算成績・場別・コース別）を返す。

    Parameters
    ----------
    racer_id : 選手登録番号 (例: "4444")
    """
    results = query_df(
        "SELECT * FROM race_results WHERE racer_id = ?", [racer_id]
    )
    if results.empty:
        return json.dumps({"error": f"選手 {racer_id} のデータなし"}, ensure_ascii=False)

    info = query_df("SELECT race_code, stadium_code, stadium_name FROM race_information")
    df = results.merge(info, on="race_code", how="left")

    racer_name = df["racer_name"].iloc[0]
    total = len(df)
    wins = len(df[df["finishing_order"] == 1])
    top2 = len(df[df["finishing_order"] <= 2])
    top3 = len(df[df["finishing_order"] <= 3])
    avg_order = df["finishing_order"].mean()
    avg_st = df["start_timing"].dropna().mean()

    overall = {
        "racer_id": racer_id,
        "racer_name": racer_name,
        "total_races": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1),
        "top2_rate": round(top2 / total * 100, 1),
        "top3_rate": round(top3 / total * 100, 1),
        "avg_finishing_order": round(avg_order, 2),
        "avg_start_timing": round(avg_st, 3) if pd.notna(avg_st) else None,
    }

    # 場別成績
    by_stadium = []
    for (code, name), g in df.groupby(["stadium_code", "stadium_name"]):
        n = len(g)
        w = len(g[g["finishing_order"] == 1])
        t3 = len(g[g["finishing_order"] <= 3])
        by_stadium.append({
            "stadium": name,
            "races": n,
            "win_rate": round(w / n * 100, 1),
            "top3_rate": round(t3 / n * 100, 1),
        })
    by_stadium.sort(key=lambda x: x["win_rate"], reverse=True)

    # コース別成績（枠番別）
    by_lane = []
    for lane in range(1, 7):
        g = df[df["lane"] == lane]
        n = len(g)
        if n == 0:
            continue
        w = len(g[g["finishing_order"] == 1])
        t3 = len(g[g["finishing_order"] <= 3])
        by_lane.append({
            "lane": lane,
            "races": n,
            "win_rate": round(w / n * 100, 1),
            "top3_rate": round(t3 / n * 100, 1),
        })

    return json.dumps({
        "overall": overall,
        "by_stadium": by_stadium,
        "by_lane": by_lane,
    }, ensure_ascii=False)


def get_racer_at_stadium(racer_id: str, stadium: str) -> str:
    """
    特定の場での選手成績を返す。

    Parameters
    ----------
    racer_id : 選手登録番号
    stadium  : 場コード(01-24)または場名
    """
    info = query_df("SELECT race_code, stadium_code, stadium_name FROM race_information")
    results = query_df(
        "SELECT * FROM race_results WHERE racer_id = ?", [racer_id]
    )
    if results.empty:
        return json.dumps({"error": f"選手 {racer_id} のデータなし"}, ensure_ascii=False)

    df = results.merge(info, on="race_code", how="left")
    df = df[(df["stadium_code"] == stadium) | (df["stadium_name"] == stadium)]

    if df.empty:
        return json.dumps({"error": f"選手 {racer_id} の場 {stadium} データなし"}, ensure_ascii=False)

    racer_name = df["racer_name"].iloc[0]
    stadium_name = df["stadium_name"].iloc[0]
    total = len(df)
    wins = len(df[df["finishing_order"] == 1])
    top3 = len(df[df["finishing_order"] <= 3])
    avg_st = df["start_timing"].dropna().mean()

    return json.dumps({
        "racer_id": racer_id,
        "racer_name": racer_name,
        "stadium": stadium_name,
        "races": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1),
        "top3_rate": round(top3 / total * 100, 1),
        "avg_finishing_order": round(df["finishing_order"].mean(), 2),
        "avg_start_timing": round(avg_st, 3) if pd.notna(avg_st) else None,
    }, ensure_ascii=False)


def get_recent_form(racer_id: str, limit: int = 10) -> str:
    """
    選手の直近N走の成績を返す。

    Parameters
    ----------
    racer_id : 選手登録番号
    limit    : 取得レース数 (デフォルト10)
    """
    results = query_df(
        "SELECT * FROM race_results WHERE racer_id = ? ORDER BY id DESC",
        [racer_id],
    )
    if results.empty:
        return json.dumps({"error": f"選手 {racer_id} のデータなし"}, ensure_ascii=False)

    info = query_df("SELECT race_code, race_date, stadium_name, race_number FROM race_information")
    df = results.head(limit).merge(info, on="race_code", how="left")

    racer_name = df["racer_name"].iloc[0]
    total = len(df)
    wins = len(df[df["finishing_order"] == 1])
    top3 = len(df[df["finishing_order"] <= 3])

    races = []
    for _, row in df.iterrows():
        races.append({
            "date": row.get("race_date"),
            "stadium": row.get("stadium_name"),
            "race_no": int(row["race_number"]) if pd.notna(row.get("race_number")) else None,
            "lane": int(row["lane"]),
            "finishing_order": int(row["finishing_order"]),
            "start_timing": round(row["start_timing"], 2) if pd.notna(row.get("start_timing")) else None,
            "race_time": row.get("race_time"),
        })

    return json.dumps({
        "racer_id": racer_id,
        "racer_name": racer_name,
        "recent_stats": {
            "races": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1),
            "top3_rate": round(top3 / total * 100, 1),
        },
        "races": races,
    }, ensure_ascii=False)


# ── Claude Tool Use 定義 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_racer_profile",
        "description": "選手の通算プロファイル（全体成績・場別・コース別）を返す。",
        "input_schema": {
            "type": "object",
            "properties": {
                "racer_id": {"type": "string", "description": "選手登録番号 (例: '4444')"},
            },
            "required": ["racer_id"],
        },
    },
    {
        "name": "get_racer_at_stadium",
        "description": "特定の場での選手成績を返す。",
        "input_schema": {
            "type": "object",
            "properties": {
                "racer_id": {"type": "string", "description": "選手登録番号"},
                "stadium": {"type": "string", "description": "場コード(01-24)または場名"},
            },
            "required": ["racer_id", "stadium"],
        },
    },
    {
        "name": "get_recent_form",
        "description": "選手の直近N走の成績と詳細を返す。",
        "input_schema": {
            "type": "object",
            "properties": {
                "racer_id": {"type": "string", "description": "選手登録番号"},
                "limit": {"type": "integer", "description": "取得レース数", "default": 10},
            },
            "required": ["racer_id"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_racer_profile": get_racer_profile,
    "get_racer_at_stadium": get_racer_at_stadium,
    "get_recent_form": get_recent_form,
}
