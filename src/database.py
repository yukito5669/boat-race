"""
Turso（libSQL）データベース管理モジュール

接続: 環境変数 TURSO_URL + TURSO_TOKEN を使用
  TURSO_URL   例: libsql://[db-name]-[org].turso.io
  TURSO_TOKEN 例: eyJ...（Turso CLIまたはダッシュボードで取得）

SQLite互換のため ? プレースホルダーをそのまま使用。
"""
import os
import time
from datetime import datetime, timezone

import libsql_client
import pandas as pd


def _with_retry(label: str, fn, *args, max_attempts: int = 10, **kwargs):
    """Turso/aiohttp の一過性ネットワーク失敗を最大 N 回吸収して fn を再実行。

    待ち時間は 3,6,12,24,48,60,60,60,60,60s（最大 60s cap、合計 ~7 分粘る）。
    Mac スリープ復帰直後の DNS / Connection reset を耐えるための想定。
    最終的に失敗したら raise。
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            wait = min(3 * (2 ** (attempt - 1)), 60)
            print(f"  [DB retry {attempt}/{max_attempts}] {label}: {type(e).__name__} -> {wait}s sleep", flush=True)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ── 場コード → 場名 マッピング ──────────────────────────────────────────────
STADIUM_MAP = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}


def _get_client() -> libsql_client.ClientSync:
    url = os.environ.get("TURSO_URL")
    token = os.environ.get("TURSO_TOKEN")
    if not url:
        raise RuntimeError(
            "環境変数 TURSO_URL が設定されていません。\n"
            "例: export TURSO_URL='libsql://[db-name]-[org].turso.io'\n"
            "    export TURSO_TOKEN='eyJ...'"
        )
    if url.startswith("libsql://"):
        url = url.replace("libsql://", "https://", 1)
    return libsql_client.create_client_sync(url=url, auth_token=token)


# ── スキーマ ─────────────────────────────────────────────────────────────────

_SCHEMA_STATEMENTS = [
    # レースメタデータ
    """
    CREATE TABLE IF NOT EXISTS race_information (
        race_code     TEXT PRIMARY KEY,
        race_date     TEXT,
        stadium_code  TEXT,
        stadium_name  TEXT,
        race_number   INTEGER,
        race_grade    TEXT,
        race_name     TEXT,
        year          INTEGER
    )
    """,
    # レース着順結果
    """
    CREATE TABLE IF NOT EXISTS race_results (
        id               INTEGER PRIMARY KEY,
        race_code        TEXT NOT NULL,
        finishing_order  INTEGER,
        lane             INTEGER,
        racer_id         TEXT,
        racer_name       TEXT,
        racer_rank       TEXT,
        motor_no         INTEGER,
        motor_top2_rate  REAL,
        motor_top3_rate  REAL,
        boat_no          INTEGER,
        boat_top2_rate   REAL,
        boat_top3_rate   REAL,
        race_time        TEXT,
        start_timing     REAL,
        course           INTEGER
    )
    """,
    # 既存テーブルへのカラム追加（IF NOT EXISTS未対応のSQLite/libSQLでもエラー無視）
    "ALTER TABLE race_results ADD COLUMN motor_top2_rate REAL",
    "ALTER TABLE race_results ADD COLUMN motor_top3_rate REAL",
    "ALTER TABLE race_results ADD COLUMN boat_top2_rate  REAL",
    "ALTER TABLE race_results ADD COLUMN boat_top3_rate  REAL",
    # 払戻金
    """
    CREATE TABLE IF NOT EXISTS payout_results (
        id           INTEGER PRIMARY KEY,
        race_code    TEXT NOT NULL,
        bet_type     TEXT,
        combination  TEXT,
        payout       INTEGER,
        popularity   INTEGER
    )
    """,
    # 確定オッズ
    """
    CREATE TABLE IF NOT EXISTS race_odds (
        id           INTEGER PRIMARY KEY,
        race_code    TEXT NOT NULL,
        bet_type     TEXT,
        combination  TEXT,
        odds         REAL,
        collected_at TEXT
    )
    """,
    # 選手マスタ
    """
    CREATE TABLE IF NOT EXISTS racer_master (
        racer_id          TEXT PRIMARY KEY,
        racer_name        TEXT,
        rank              TEXT,
        branch            TEXT,
        total_races       INTEGER,
        wins              INTEGER,
        top2              INTEGER,
        top3              INTEGER,
        win_rate          REAL,
        top2_rate         REAL,
        top3_rate         REAL,
        avg_start_timing  REAL,
        updated_at        TEXT
    )
    """,
    # 選手条件別統計
    """
    CREATE TABLE IF NOT EXISTS racer_split_stats (
        id          INTEGER PRIMARY KEY,
        racer_id    TEXT NOT NULL,
        split_type  TEXT NOT NULL,
        split_value TEXT NOT NULL,
        races       INTEGER,
        wins        INTEGER,
        top3        INTEGER,
        win_rate    REAL,
        top3_rate   REAL
    )
    """,
    # 賭け記録
    """
    CREATE TABLE IF NOT EXISTS bet_records (
        id           INTEGER PRIMARY KEY,
        race_code    TEXT,
        race_date    TEXT,
        race_name    TEXT,
        bet_type     TEXT,
        combination  TEXT,
        amount       INTEGER,
        is_hit       INTEGER,
        payout_total INTEGER,
        profit       INTEGER,
        memo         TEXT,
        created_at   TEXT
    )
    """,
    # インデックス
    "CREATE INDEX IF NOT EXISTS idx_ri_grade      ON race_information(race_grade)",
    "CREATE INDEX IF NOT EXISTS idx_ri_year        ON race_information(year)",
    "CREATE INDEX IF NOT EXISTS idx_ri_stadium     ON race_information(stadium_code)",
    "CREATE INDEX IF NOT EXISTS idx_ri_date        ON race_information(race_date)",
    "CREATE INDEX IF NOT EXISTS idx_rr_race_code   ON race_results(race_code)",
    "CREATE INDEX IF NOT EXISTS idx_rr_racer_id    ON race_results(racer_id)",
    "CREATE INDEX IF NOT EXISTS idx_pr_race_code   ON payout_results(race_code)",
    "CREATE INDEX IF NOT EXISTS idx_pr_bet_type    ON payout_results(bet_type)",
    "CREATE INDEX IF NOT EXISTS idx_ro_race_code   ON race_odds(race_code)",
    "CREATE INDEX IF NOT EXISTS idx_rm_name        ON racer_master(racer_name)",
    "CREATE INDEX IF NOT EXISTS idx_rss_racer      ON racer_split_stats(racer_id)",
    "CREATE INDEX IF NOT EXISTS idx_rss_type       ON racer_split_stats(split_type, split_value)",
    "CREATE INDEX IF NOT EXISTS idx_br_race_code   ON bet_records(race_code)",
]


def init_db():
    """全テーブル・インデックスを作成。

    ALTER TABLE ADD COLUMN は既存カラムがあるとエラーになるが、
    libSQLは IF NOT EXISTS をサポートしないため try/except で吸収する。
    """
    client = _get_client()
    try:
        for stmt in _SCHEMA_STATEMENTS:
            try:
                client.execute(stmt)
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    continue
                raise
        print(f"[DB] スキーマ初期化完了（{len(_SCHEMA_STATEMENTS)}ステートメント実行）")
    finally:
        client.close()


# ── CRUD: race_information ──────────────────────────────────────────────────

def race_exists(race_code: str) -> bool:
    client = _get_client()
    try:
        rs = client.execute("SELECT 1 FROM race_information WHERE race_code = ?", [race_code])
        return len(rs.rows) > 0
    finally:
        client.close()


def insert_race_information(data: dict):
    client = _get_client()
    try:
        client.execute(
            """
            INSERT OR IGNORE INTO race_information
                (race_code, race_date, stadium_code, stadium_name, race_number, race_grade, race_name, year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                data["race_code"], data["race_date"], data["stadium_code"],
                data["stadium_name"], data["race_number"], data.get("race_grade", "一般"),
                data.get("race_name", ""), data["year"],
            ],
        )
    finally:
        client.close()


# ── CRUD: race_results ──────────────────────────────────────────────────────

def insert_race_results(race_code: str, results: list[dict]):
    """6艇分をまとめて batch でINSERT（個別execute だと往復で数秒かかるため）"""
    if not results:
        return
    client = _get_client()
    try:
        sql = """
        INSERT INTO race_results
            (race_code, finishing_order, lane, racer_id, racer_name, racer_rank,
             motor_no, motor_top2_rate, motor_top3_rate,
             boat_no, boat_top2_rate, boat_top3_rate,
             race_time, start_timing, course)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        stmts = [
            (sql, [
                race_code, r.get("finishing_order"), r.get("lane"),
                r.get("racer_id"), r.get("racer_name"), r.get("racer_rank"),
                r.get("motor_no"), r.get("motor_top2_rate"), r.get("motor_top3_rate"),
                r.get("boat_no"),  r.get("boat_top2_rate"),  r.get("boat_top3_rate"),
                r.get("race_time"), r.get("start_timing"), r.get("course"),
            ])
            for r in results
        ]
        client.batch(stmts)
    finally:
        client.close()


def update_racelist_for_race(race_code: str, lane_data: dict[int, dict]) -> int:
    """既存のrace_resultsに racelist情報をUPDATE（Turso瞬断にはリトライ）"""
    if not lane_data:
        return 0
    return _with_retry(f"update_racelist {race_code}", _update_racelist_inner, race_code, lane_data)


def _update_racelist_inner(race_code: str, lane_data: dict[int, dict]) -> int:
    client = _get_client()
    n = 0
    try:
        stmts = []
        for lane, info in lane_data.items():
            stmts.append((
                """
                UPDATE race_results
                SET racer_rank      = COALESCE(?, racer_rank),
                    motor_no        = COALESCE(?, motor_no),
                    motor_top2_rate = COALESCE(?, motor_top2_rate),
                    motor_top3_rate = COALESCE(?, motor_top3_rate),
                    boat_no         = COALESCE(?, boat_no),
                    boat_top2_rate  = COALESCE(?, boat_top2_rate),
                    boat_top3_rate  = COALESCE(?, boat_top3_rate)
                WHERE race_code = ? AND lane = ?
                """,
                [
                    info.get("racer_rank"),
                    info.get("motor_no"), info.get("motor_top2_rate"), info.get("motor_top3_rate"),
                    info.get("boat_no"),  info.get("boat_top2_rate"),  info.get("boat_top3_rate"),
                    race_code, lane,
                ],
            ))
        if stmts:
            client.batch(stmts)
            n = len(stmts)
    finally:
        client.close()
    return n


# ── CRUD: payout_results ────────────────────────────────────────────────────

def insert_payout_results(race_code: str, payouts: list[dict]):
    """払戻金をまとめて batch でINSERT"""
    if not payouts:
        return
    client = _get_client()
    try:
        sql = """
        INSERT INTO payout_results
            (race_code, bet_type, combination, payout, popularity)
        VALUES (?, ?, ?, ?, ?)
        """
        stmts = [
            (sql, [race_code, p["bet_type"], p["combination"], p["payout"], p.get("popularity")])
            for p in payouts
        ]
        client.batch(stmts)
    finally:
        client.close()


def save_race_bundle(
    race_info: dict,
    results: list[dict],
    payouts: list[dict],
):
    """1レース分のメタ・着順・払戻を **1接続・1バッチ** で保存する高速版。

    バックフィル時に insert_race_information + insert_race_results + insert_payout_results を
    別々に呼ぶと、Turso接続オープンクローズが3回発生して秒単位の遅延になるためまとめる。
    Turso瞬断には `_with_retry` で耐性。
    """
    _with_retry(f"save_race_bundle {race_info.get('race_code')}", _save_race_bundle_inner, race_info, results, payouts)


def _save_race_bundle_inner(race_info, results, payouts):
    client = _get_client()
    try:
        stmts: list[tuple[str, list]] = []

        stmts.append((
            """
            INSERT OR IGNORE INTO race_information
                (race_code, race_date, stadium_code, stadium_name, race_number, race_grade, race_name, year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                race_info["race_code"], race_info["race_date"], race_info["stadium_code"],
                race_info["stadium_name"], race_info["race_number"],
                race_info.get("race_grade", "一般"),
                race_info.get("race_name", ""), race_info["year"],
            ],
        ))

        rr_sql = """
        INSERT INTO race_results
            (race_code, finishing_order, lane, racer_id, racer_name, racer_rank,
             motor_no, motor_top2_rate, motor_top3_rate,
             boat_no, boat_top2_rate, boat_top3_rate,
             race_time, start_timing, course)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for r in results:
            stmts.append((rr_sql, [
                race_info["race_code"], r.get("finishing_order"), r.get("lane"),
                r.get("racer_id"), r.get("racer_name"), r.get("racer_rank"),
                r.get("motor_no"), r.get("motor_top2_rate"), r.get("motor_top3_rate"),
                r.get("boat_no"),  r.get("boat_top2_rate"),  r.get("boat_top3_rate"),
                r.get("race_time"), r.get("start_timing"), r.get("course"),
            ]))

        pr_sql = """
        INSERT INTO payout_results
            (race_code, bet_type, combination, payout, popularity)
        VALUES (?, ?, ?, ?, ?)
        """
        for p in payouts or []:
            stmts.append((pr_sql, [
                race_info["race_code"], p["bet_type"], p["combination"],
                p["payout"], p.get("popularity"),
            ]))

        client.batch(stmts)
    finally:
        client.close()


# ── CRUD: race_odds ─────────────────────────────────────────────────────────

def race_odds_exists(race_code: str) -> bool:
    client = _get_client()
    try:
        rs = client.execute("SELECT 1 FROM race_odds WHERE race_code = ? LIMIT 1", [race_code])
        return len(rs.rows) > 0
    finally:
        client.close()


def insert_race_odds(race_code: str, odds_list: list[dict]):
    """1レース分のオッズをバッチ送信（Turso瞬断にはリトライ）。"""
    if not odds_list:
        return
    _with_retry(f"insert_race_odds {race_code}", _insert_race_odds_inner, race_code, odds_list)


def _insert_race_odds_inner(race_code: str, odds_list: list[dict]):
    client = _get_client()
    try:
        now = datetime.now(timezone.utc).isoformat()
        stmts = [
            (
                """
                INSERT INTO race_odds
                    (race_code, bet_type, combination, odds, collected_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [race_code, o["bet_type"], o["combination"], o["odds"], now],
            )
            for o in odds_list
        ]
        client.batch(stmts)
    finally:
        client.close()


# ── CRUD: bet_records ───────────────────────────────────────────────────────

def insert_bet_record(data: dict):
    client = _get_client()
    try:
        now = datetime.now(timezone.utc).isoformat()
        client.execute(
            """
            INSERT INTO bet_records
                (race_code, race_date, race_name, bet_type, combination,
                 amount, is_hit, payout_total, profit, memo, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                data["race_code"], data.get("race_date"), data.get("race_name"),
                data["bet_type"], data["combination"], data["amount"],
                data.get("is_hit"), data.get("payout_total"), data.get("profit"),
                data.get("memo"), now,
            ],
        )
    finally:
        client.close()


# ── クエリ ──────────────────────────────────────────────────────────────────

def query_df(sql: str, params: list | None = None) -> pd.DataFrame:
    """SQL実行結果をDataFrameで返す"""
    client = _get_client()
    try:
        rs = client.execute(sql, params or [])
        if not rs.rows:
            return pd.DataFrame()
        columns = list(rs.columns)
        return pd.DataFrame([list(row) for row in rs.rows], columns=columns)
    finally:
        client.close()


def build_racer_master() -> int:
    """race_resultsから選手別に集計し、racer_masterをupsertする。

    rank/branchは別ソース（出走表）からの取得が必要なためNULL保留。
    finishing_order=99（転覆・失格等）はwin/top2/top3から除外するが、total_racesには含める。

    Returns: upsertした選手数
    """
    df = query_df(
        """
        SELECT racer_id, racer_name, finishing_order, start_timing
        FROM race_results
        WHERE racer_id IS NOT NULL AND racer_id != ''
        """
    )
    if df.empty:
        print("[racer_master] race_resultsにデータなし")
        return 0

    # 最新の選手名を採用（同じracer_idで表記揺れがあった場合の保険）
    latest_name = (
        df.dropna(subset=["racer_name"])
        .groupby("racer_id")["racer_name"]
        .agg(lambda s: s.iloc[-1])
    )

    grouped = df.groupby("racer_id")
    now = datetime.now(timezone.utc).isoformat()

    client = _get_client()
    count = 0
    try:
        for racer_id, g in grouped:
            total = len(g)
            valid = g[g["finishing_order"] < 99]
            wins = int((valid["finishing_order"] == 1).sum())
            top2 = int((valid["finishing_order"] <= 2).sum())
            top3 = int((valid["finishing_order"] <= 3).sum())
            avg_st = g["start_timing"].dropna().mean()

            client.execute(
                """
                INSERT INTO racer_master
                    (racer_id, racer_name, rank, branch, total_races, wins, top2, top3,
                     win_rate, top2_rate, top3_rate, avg_start_timing, updated_at)
                VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(racer_id) DO UPDATE SET
                    racer_name       = excluded.racer_name,
                    total_races      = excluded.total_races,
                    wins             = excluded.wins,
                    top2             = excluded.top2,
                    top3             = excluded.top3,
                    win_rate         = excluded.win_rate,
                    top2_rate        = excluded.top2_rate,
                    top3_rate        = excluded.top3_rate,
                    avg_start_timing = excluded.avg_start_timing,
                    updated_at       = excluded.updated_at
                """,
                [
                    racer_id,
                    latest_name.get(racer_id, ""),
                    total,
                    wins,
                    top2,
                    top3,
                    round(wins / total * 100, 2) if total else 0.0,
                    round(top2 / total * 100, 2) if total else 0.0,
                    round(top3 / total * 100, 2) if total else 0.0,
                    round(float(avg_st), 4) if pd.notna(avg_st) else None,
                    now,
                ],
            )
            count += 1
    finally:
        client.close()

    print(f"[racer_master] {count} 選手をupsertしました")
    return count


def get_db_stats() -> dict:
    """各テーブルの行数を取得"""
    tables = [
        "race_information", "race_results", "payout_results",
        "race_odds", "racer_master", "racer_split_stats", "bet_records",
    ]
    client = _get_client()
    try:
        stats = {}
        for t in tables:
            rs = client.execute(f"SELECT COUNT(*) FROM {t}")
            stats[t] = rs.rows[0][0]
        return stats
    finally:
        client.close()
