# 仮説検証セッション 引き継ぎ書

作成日: 2026-06-06  
引き継ぎ元: データ収集セッション  
引き継ぎ先: 仮説検証セッション（U-001 クロスバリデーション + U-002〜U-005 本格分析）

---

## 1. このセッションのスコープ

以下を担当してください。**データ収集パイプラインの修正・拡張は不要**です（別セッションで2024年バックフィルを並行実行中）。

### 担当タスク

1. **U-001 のクロスバリデーション** — 仮説 #001 (予備) を本検証へ
2. **U-002 〜 U-005 の本格分析** — 未検証4仮説の検証

担当外:
- 2024年バックフィル（別セッションのバックグラウンドプロセス8本が稼働中）
- 過去2年(2023年以前)拡張（2024完了後に別途判断）
- データ収集コードの追加（必要があれば申告してください、コード追加はしない）

---

## 2. 現在のDB状態

### テーブル件数 (2026-06-06 時点)

| テーブル | 件数 | 備考 |
|---------|------|------|
| race_information | 62,571 | 2024-01-01 〜 2026-06-04 |
| race_results | 375,636 | 約6 / レース、`motor_no` 含む全カラム埋まり済 |
| payout_results | 625,475 | 約10 / レース |
| race_odds | 2,668,971 行 / **22,354 レース** | 3連単120組合せ × レース数 |
| racer_master | 1,667 | 集計可能。再構築は `python main.py build-racer-master` |
| racelist埋め率 | **62,554 / 62,571 (99.97%)** | racer_rank/motor_no/boat_no/機力指標 全有り |

### オッズカバレッジ（重要・偏りあり）

| 期間 | レース数 | オッズあり | カバー率 |
|------|---------|----------|---------|
| 2024年全期 | 86 | 0 | 0% (件数自体ごく僅か、GHA早期収集分のみ) |
| **2025年 1-7月** | ~31,000 | 0 | **0%** ← 古すぎてオッズ取得不可 |
| 2025年 8月 | 4,721 | 35 | 0.7% |
| 2025年 10-12月 | 11,388 | 9,452 | ~83% |
| **2026年全期** | 12,867 | 12,867 | **100%** |

→ **オッズを使う分析 (U-001, U-005 の一部) は 2025年10月以降 + 2026年 に限定**。  
→ オッズ不要分析 (U-002, U-003, U-004) は **全62,000 レース** 使える。

### データ範囲

- min_date: 2024-01-01（ただし2024年は86件のみ・進行中）
- max_date: 2026-06-04（GHA日次で延長中）

### 2024年バックフィル進行中

別セッションで 8 並列ワーカーが 2024-01-01 〜 2024-12-31 を取得中（W1〜W8、`/tmp/boat-2024-W*.log`）。**触らないでください**。終わるまで race_information の件数は増え続けます。

完了見込み: 約3-5日（2025年と同様）。完了後に 2024年全件 + 部分的オッズが追加されます。

---

## 3. 仮説リスト（最新版）

詳細は [analysis/simulation_log.md](simulation_log.md) を参照。

| ID | タイトル | 状態 | 必要データ |
|----|---------|------|-----------|
| #001 | 3連単 min(1-X-Y) でレース構造を4分類 | 予備検証済、本検証待ち | odds |
| U-001 | (#001の本検証) | 未 | odds |
| U-002 | 場別1号艇勝率の偏差を利用 | 未 | results のみ |
| U-003 | STタイミングと勝率の関係 | 未 | results のみ |
| U-004 | 選手ランク組み合わせと配当 | 未 | results + payouts |
| U-005 | 「買わない判断」の最適化 | 未 | odds + 上記いずれか |

### 仮説 #001 (予備) の結果 (要再現)

サンプル 10,034レース (主に2026年) で:

| パターン | 件数 | 1号艇勝率 | 本命1点ROI |
|---------|------|----------|------------|
| A:断然 (fav ≤ 3.5) | 180 | 79.4% | **87.2%** |
| B:優勢 (≤ 6.0) | 2,488 | 72.7% | **83.6%** |
| C:拮抗 (≤ 10.0) | 4,286 | 60.1% | 75.5% |
| D:混戦 (> 10.0) | 3,080 | 32.7% | 70.6% |

A/B は標準控除率(75%)を超えるROIで「エッジあり候補」。  
ただしクロスバリデーション未実施 → 過学習の可能性大。U-001 本検証で再現性を確認すること。

---

## 4. クロスバリデーション方針

**プロジェクトルール (CLAUDE.md より)**:
> 過学習回避: Leave-one-year-outクロスバリデーション必須

ただし現状オッズが取れているのは 2025年10月-2026年6月 (約9ヶ月) のみ。**完全な年単位 leave-one-out は不可能**なので、以下に分割するのが現実的：

### 推奨分割 (時系列ブロック)

| ブロック | 期間 | 推定レース数 (odds付) |
|---------|------|---------------------|
| Block A | 2025-10 〜 2025-12 | ~9,500 |
| Block B | 2026-01 〜 2026-03 | ~4,500 |
| Block C | 2026-04 〜 2026-06 | ~8,500 |

→ 3-fold cross-validation。各ブロックを順番に検証用にし、残り2ブロックで閾値を最適化。3 fold すべてで控除率超ならエッジ確証度高。

### 2024年バックフィル完了後 (数日後)

GHA経由ではなくバックフィル経由で取った2024年データはオッズ無し。よって**オッズ系仮説のクロスバリデーション拡張には寄与しない**。ただし U-002/U-003/U-004 のような **レース結果のみで完結する仮説** は2024年データを含めて leave-one-year-out（2024 vs 2025 vs 2026 ←年単位）が可能になる。

---

## 5. 環境セットアップ

```bash
cd /Users/yukiito/developments/boat-race
source .venv/bin/activate  # 既にあり
```

`.env` に `TURSO_URL`, `TURSO_TOKEN`, `ANTHROPIC_API_KEY` あり。  
コード内 main.py が `.env` を `os.environ.setdefault` で読み込みます。スクリプトから直接使う場合の定型:

```python
import os
for line in open('.env'):
    if '=' in line:
        k, _, v = line.strip().partition('=')
        os.environ.setdefault(k.strip(), v.strip())
```

---

## 6. 既存ツール

### `src/analyzer.py` — Claude Tool Use 用統計関数

- `get_lane_win_rate(stadium, grade)` — 枠番別勝率
- `get_bet_type_roi(bet_type, grade)`
- `get_popularity_roi(bet_type)` — 人気順別ROI
- `get_odds_pattern_analysis(grade)` — **#001 の本体実装**。全データで再走可
- `get_start_timing_analysis(stadium)` — U-003 の素材
- `get_stadium_summary()` — U-002 の素材

### `src/racer_analyzer.py` — 選手別分析

- `get_racer_profile(racer_id)` — 通算成績
- `get_racer_at_stadium(racer_id, stadium)`
- `get_recent_form(racer_id, limit)`

### `src/database.py` — DB アクセス

- `query_df(sql, params)` — pandas DataFrame で結果取得
- 標準的な SELECT を直接書いて使うのが速い

### CLI

```bash
python main.py db-stats              # テーブル件数
python main.py build-racer-master    # racer_master を race_results から再構築
python main.py analyze               # 要点サマリーを表示
python main.py recommend --race-input race_input.json  # Claude Tool Use 推薦
```

---

## 7. 検証結果の記録

すべての仮説検証は [analysis/simulation_log.md](simulation_log.md) に追記してください。フォーマットは冒頭の「フォーマット」セクション参照。

- 番号は #002 から始める（#001 は予備として既存）
- **クロスバリデーション結果は必ず記録**。年/ブロック単位の表で fold ROI を並べる
- **採用/棄却/要追加検証** を明示
- 棄却理由は「サンプル不足」「過学習」「閾値固有のチェリーピック」など具体的に

---

## 8. 注意事項

### コードに触らない

データ収集パイプラインのコード（`src/collector.py`, `src/database.py`, `main.py`の collect系）は **本セッションでは変更しないでください**。新規分析関数を `src/analyzer.py` に追加するのは OK。

### バックグラウンド競合

2024年バックフィルが Turso に書き込み中。読み取りは問題ないが、**大量同時クエリは控えめに**（Turso料金/レート制限を回避）。

### Turso瞬断

ネットワーク瞬断時、書き込みは `_with_retry`（最大10回・~7分粘る）が吸収する。読み取りクエリ単体には retry が無いので、長時間の連続クエリは try/except で受けるのが安全。

### バックフィルの監視責任

このセッションは **バックフィル監視の責任を持ちません**。プロセスが死んでも引き継ぎ元セッションが対応します。

---

## 9. 推奨 First Step

```python
# 1. 現状確認
from src.database import query_df
df = query_df("SELECT COUNT(*) AS races, MIN(race_date), MAX(race_date) FROM race_information")
print(df)

# 2. オッズ付きデータの分布把握
from src.analyzer import get_odds_pattern_analysis
import json
r = json.loads(get_odds_pattern_analysis())
print(json.dumps(r, ensure_ascii=False, indent=2))

# 3. ブロック分割でクロスバリデーション
#   → analyzer.py に get_odds_pattern_analysis_by_block(start, end) を追加してもよい
```

---

## 10. 完了の定義

以下が揃ったら本セッション完了:

- [ ] U-001 (3-fold CV) の結果が simulation_log に記載
- [ ] U-002 (場別1号艇勝率戦略) の結果が記載
- [ ] U-003 (ST と勝率) の結果が記載
- [ ] U-004 (選手ランクと配当) の結果が記載
- [ ] U-005 (買わない判断) の結果が記載
- [ ] 各仮説に **採用 / 棄却 / 要追加検証** が明示されている
- [ ] エッジが確認された仮説については「賭け方の運用ルール」が文章化されている

困ったら、ユーザーに「現状の sample size でこれ以上進めるべきか」を確認してから判断してください。
