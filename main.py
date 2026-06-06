"""
boat-race CLI エントリーポイント

Usage:
    python main.py collect --date 20260409 [--stadium 06] [--force]
    python main.py collect --date-range 2026-01-01 2026-03-31 [--stadium 06]
    python main.py db-stats
    python main.py init-db
"""
import argparse
import os
import sys


def _load_env():
    """`.env` ファイルから環境変数を読み込み"""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


def cmd_init_db(_args):
    from src.database import init_db
    init_db()


def cmd_db_stats(_args):
    from src.database import get_db_stats
    stats = get_db_stats()
    print("\n=== DB Statistics ===")
    for table, count in stats.items():
        print(f"  {table:25s}: {count:>8,} rows")
    print()


def cmd_build_racer_master(_args):
    from src.database import build_racer_master
    build_racer_master()


def cmd_collect_odds(args):
    from src.collector import collect_missing_odds
    collect_missing_odds(
        limit=args.limit,
        start_date=args.start_date,
        end_date=args.end_date,
    )


def cmd_collect_racelist(args):
    from src.collector import collect_missing_racelist
    collect_missing_racelist(
        limit=args.limit,
        start_date=args.start_date,
        end_date=args.end_date,
    )


def cmd_collect_grade(args):
    from src.collector import collect_missing_grade
    collect_missing_grade(
        limit=args.limit,
        start_date=args.start_date,
        end_date=args.end_date,
    )


def cmd_collect(args):
    if args.date:
        from src.collector import collect_date
        stadium_codes = [args.stadium] if args.stadium else None
        collect_date(args.date, stadium_codes=stadium_codes, force=args.force)

    elif args.date_range:
        from src.collector import collect_date_range
        start, end = args.date_range
        stadium_codes = [args.stadium] if args.stadium else None
        collect_date_range(start, end, stadium_codes=stadium_codes, force=args.force)

    else:
        print("Error: --date or --date-range が必要です")
        sys.exit(1)


def cmd_analyze(_args):
    from src.analyzer import get_lane_win_rate, get_stadium_summary
    import json

    print("\n=== 場別1号艇勝率 ===")
    data = json.loads(get_stadium_summary())
    if "stadiums" in data:
        print(f"{'場名':8s} {'レース数':>8s} {'1号艇勝率':>10s}")
        print("-" * 30)
        for s in data["stadiums"]:
            print(f"{s['stadium_name']:8s} {s['total_races']:>8d} {s['lane1_win_rate']:>9.1f}%")

    print("\n=== 全体枠番別勝率 ===")
    data = json.loads(get_lane_win_rate())
    if "lane_stats" in data:
        print(f"{'枠':>4s} {'勝率':>8s} {'2連対率':>8s} {'3連対率':>8s}")
        print("-" * 32)
        for ls in data["lane_stats"]:
            print(f"{ls['lane']:>4d} {ls['win_rate']:>7.1f}% {ls['top2_rate']:>7.1f}% {ls['top3_rate']:>7.1f}%")
    print()


def cmd_recommend(args):
    import json
    from src.recommender import recommend

    with open(args.race_input) as f:
        race_info = json.load(f)

    result = recommend(race_info, verbose=True)
    print("\n" + "=" * 60)
    print(result)


def main():
    _load_env()

    parser = argparse.ArgumentParser(description="boat-race CLI")
    subparsers = parser.add_subparsers(dest="command")

    # init-db
    subparsers.add_parser("init-db", help="DBスキーマ初期化")

    # db-stats
    subparsers.add_parser("db-stats", help="DB統計表示")

    # build-racer-master
    subparsers.add_parser("build-racer-master", help="racer_masterをrace_resultsから再構築")

    # collect-odds
    p_co = subparsers.add_parser("collect-odds", help="race_odds未収集レースの3連単確定オッズを後追い取得")
    p_co.add_argument("--limit", type=int, help="処理する最大レース数")
    p_co.add_argument("--start-date", help="対象下限 YYYY-MM-DD (inclusive)")
    p_co.add_argument("--end-date",   help="対象上限 YYYY-MM-DD (inclusive)")

    # collect-racelist
    p_cr = subparsers.add_parser("collect-racelist", help="出走表からモーター/ボート番号・選手ランク・機力指標を後追い取得")
    p_cr.add_argument("--limit", type=int, help="処理する最大レース数")
    p_cr.add_argument("--start-date", help="対象下限 YYYY-MM-DD (inclusive)")
    p_cr.add_argument("--end-date",   help="対象上限 YYYY-MM-DD (inclusive)")

    # collect-grade
    p_cg = subparsers.add_parser("collect-grade", help="race_grade='一般' のレースを raceresult から再判定して埋め直す (stadium-day単位)")
    p_cg.add_argument("--limit", type=int, help="処理する最大 stadium-day 数")
    p_cg.add_argument("--start-date", help="対象下限 YYYY-MM-DD (inclusive)")
    p_cg.add_argument("--end-date",   help="対象上限 YYYY-MM-DD (inclusive)")

    # collect
    p_collect = subparsers.add_parser("collect", help="レースデータ収集")
    p_collect.add_argument("--date", help="日付 (YYYYMMDD)")
    p_collect.add_argument("--date-range", nargs=2, metavar=("START", "END"),
                           help="期間 (YYYY-MM-DD YYYY-MM-DD)")
    p_collect.add_argument("--stadium", help="場コード (01-24)")
    p_collect.add_argument("--force", action="store_true", help="既存データも再取得")

    # analyze
    subparsers.add_parser("analyze", help="統計分析サマリー表示")

    # recommend
    p_recommend = subparsers.add_parser("recommend", help="Claude APIでレース推薦")
    p_recommend.add_argument("--race-input", required=True, help="レース情報JSONファイル")

    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "db-stats":
        cmd_db_stats(args)
    elif args.command == "build-racer-master":
        cmd_build_racer_master(args)
    elif args.command == "collect-odds":
        cmd_collect_odds(args)
    elif args.command == "collect-racelist":
        cmd_collect_racelist(args)
    elif args.command == "collect-grade":
        cmd_collect_grade(args)
    elif args.command == "collect":
        cmd_collect(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "recommend":
        cmd_recommend(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
