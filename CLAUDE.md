# boat-race: 競艇データ分析・予測システム

## 概要
BOATRACE公式サイトからレースデータを収集し、統計分析・AI予測でROI最大化を目指すシステム。
horse-raceプロジェクト（競馬）のアーキテクチャを競艇に転用。

## 技術スタック
- Python 3.11+
- Turso (libSQL) — リモートDB
- requests + BeautifulSoup4 — スクレイピング
- pandas + numpy — データ分析
- anthropic — Claude API (Tool Use)
- GitHub Actions — 定期データ収集

## 環境セットアップ
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 環境変数 (.env)
```
TURSO_URL=libsql://boat-race-xxx.turso.io
TURSO_TOKEN=eyJ...
ANTHROPIC_API_KEY=sk-ant-...
```
コード内で `export $(cat .env | xargs)` で読み込み。

## データベーススキーマ

### race_information — レースメタデータ
| Column | Type | Description |
|--------|------|-------------|
| race_code | TEXT PK | `{YYYYMMDD}_{jcd:02d}_{rno:02d}` |
| race_date | TEXT | YYYY-MM-DD |
| stadium_code | TEXT | 場コード(01-24) |
| stadium_name | TEXT | 場名 |
| race_number | INTEGER | レース番号(1-12) |
| race_grade | TEXT | SG/G1/G2/G3/一般 |
| race_name | TEXT | レース名 |
| year | INTEGER | 開催年 |

### race_results — レース着順結果
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | 自動採番 |
| race_code | TEXT FK | race_information参照 |
| finishing_order | INTEGER | 着順(1-6, 転覆等は99) |
| lane | INTEGER | 枠番(1-6) |
| racer_id | TEXT | 選手登録番号 |
| racer_name | TEXT | 選手名 |
| racer_rank | TEXT | A1/A2/B1/B2 |
| motor_no | INTEGER | モーター番号 |
| boat_no | INTEGER | ボート番号 |
| race_time | TEXT | レースタイム |
| start_timing | REAL | STタイミング(秒) |
| course | INTEGER | 進入コース(1-6) |

### payout_results — 払戻金
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | 自動採番 |
| race_code | TEXT FK | race_information参照 |
| bet_type | TEXT | 3連単/3連複/2連単/2連複/拡連複/単勝/複勝 |
| combination | TEXT | 組み合わせ(例: "1-2-3") |
| payout | INTEGER | 払戻金(100円当たり) |
| popularity | INTEGER | 人気順 |

### race_odds — 確定オッズ
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | 自動採番 |
| race_code | TEXT FK | race_information参照 |
| bet_type | TEXT | 券種 |
| combination | TEXT | 組み合わせ |
| odds | REAL | オッズ |
| collected_at | TEXT | 収集日時(UTC) |

### racer_master — 選手マスタ
| Column | Type | Description |
|--------|------|-------------|
| racer_id | TEXT PK | 選手登録番号 |
| racer_name | TEXT | 選手名 |
| rank | TEXT | 最新ランク |
| branch | TEXT | 支部 |
| total_races | INTEGER | 通算出走数 |
| wins | INTEGER | 1着回数 |
| top2 | INTEGER | 2着以内 |
| top3 | INTEGER | 3着以内 |
| win_rate | REAL | 勝率 |
| top2_rate | REAL | 2連対率 |
| top3_rate | REAL | 3連対率 |
| avg_start_timing | REAL | 平均STタイミング |
| updated_at | TEXT | 更新日時 |

### racer_split_stats — 選手条件別統計
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | 自動採番 |
| racer_id | TEXT FK | 選手登録番号 |
| split_type | TEXT | stadium/course/wind/wave等 |
| split_value | TEXT | 条件値 |
| races | INTEGER | 出走数 |
| wins | INTEGER | 1着回数 |
| top3 | INTEGER | 3着以内 |
| win_rate | REAL | 勝率 |
| top3_rate | REAL | 3連対率 |

### bet_records — 賭け記録
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | 自動採番 |
| race_code | TEXT FK | race_information参照 |
| race_date | TEXT | 日付 |
| race_name | TEXT | レース名 |
| bet_type | TEXT | 券種 |
| combination | TEXT | 組み合わせ |
| amount | INTEGER | 金額(円) |
| is_hit | INTEGER | 的中フラグ |
| payout_total | INTEGER | 払戻金 |
| profit | INTEGER | 損益 |
| memo | TEXT | メモ |
| created_at | TEXT | 作成日時 |

## データソース: BOATRACE公式

### URL パターン
- レース結果: `https://www.boatrace.jp/owpc/pc/race/raceresult?hd=YYYYMMDD&jcd=XX&rno=XX`
- 結果一覧: `https://www.boatrace.jp/owpc/pc/race/resultlist?jcd=XX&hd=YYYYMMDD`
- オッズ(3連単): `https://www.boatrace.jp/owpc/pc/race/odds3t?rno=XX&jcd=XX&hd=YYYYMMDD`
- 月間スケジュール: `https://www.boatrace.jp/owpc/pc/race/monthlyschedule?ym=YYYYMM`

### 場コード一覧
01:桐生, 02:戸田, 03:江戸川, 04:平和島, 05:多摩川, 06:浜名湖,
07:蒲郡, 08:常滑, 09:津, 10:三国, 11:びわこ, 12:住之江,
13:尼崎, 14:鳴門, 15:丸亀, 16:児島, 17:宮島, 18:徳山,
19:下関, 20:若松, 21:芦屋, 22:福岡, 23:唐津, 24:大村

### スクレイピングルール
- リクエスト間隔: 1.5秒以上
- 差分収集: DB既存分はスキップ
- User-Agent設定あり

## CLIコマンド
```bash
# データ収集
python main.py collect --date 2026-04-01 --stadium 06    # 特定日・特定場
python main.py collect --month 2026-04                    # 月単位収集
python main.py collect --date-range 2026-01-01 2026-03-31 # 期間収集

# DB統計
python main.py db-stats

# 選手マスタ更新
python main.py build-racer-master

# 分析（Claude API）
python main.py analyze
python main.py recommend --race-input race_input.json

# 賭け記録
python main.py bet add --race-code XXX --bet-type 3連単 --combination "1-2-3" --amount 100
python main.py bet result --race-code XXX
python main.py bet summary
```

## 分析ツール (Claude Tool Use)

### analyzer.py
- `get_lane_win_rate(stadium, grade)` — 枠番別勝率
- `get_course_win_rate(stadium)` — 進入コース別勝率
- `get_bet_type_roi(bet_type, grade)` — 券種別ROI
- `get_popularity_roi(bet_type)` — 人気順別的中率・ROI
- `get_odds_pattern_analysis(grade)` — オッズパターン分類
- `get_start_timing_analysis(stadium)` — STタイミング分析

### racer_analyzer.py
- `get_racer_profile(racer_id)` — 選手プロファイル
- `get_racer_at_stadium(racer_id, stadium)` — 場別成績
- `get_recent_form(racer_id, limit)` — 直近N走分析

## GitHub Actions
- `.github/workflows/collect.yml` — 日次全場レース結果収集
- Secrets: `TURSO_URL`, `TURSO_TOKEN`, `ANTHROPIC_API_KEY`

## 分析方針
- **過学習回避**: Leave-one-year-outクロスバリデーション必須
- **シミュレーション記録**: analysis/simulation_log.md に全仮説を番号付きで記録
- **「買わない判断」が最重要**: 全レースに賭けるより、特定パターン見送りでROI改善
