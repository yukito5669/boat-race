## 1. このセッションのスコープ

データ収集パイプラインで **`race_grade` が全レース「一般」になっている問題** を調査・修正してください。仮説検証セッション (本セッションと並行) からは独立に作業可能です。

### 担当タスク

1. **原因調査**: なぜ `race_grade` が常に "一般" になるのか特定
2. **修正実装**: グレード(SG/G1/G2/G3/一般)を正しく取得できるよう collector を修正
3. **過去データ補完**: 既存62,000+レースに grade を後付けで埋める (再スクレイピング or 別ページ参照)

担当外:
- 仮説検証・分析 (本セッションが担当)
- 2024年バックフィル監視 (引き継ぎ元セッションが担当)

---

## 2. 問題の現状

### DB の現状
```sql
SELECT race_grade, COUNT(*) FROM race_information GROUP BY race_grade;
-- race_grade | n
-- 一般       | 62747   ← 全件これ
```

2024-01-01 〜 2026-06-04 の **全62,747レースが "一般"** になっており、SG/G1/G2/G3 の判別ができていません。実際にはこの期間中に SG (グランプリ・オーシャンカップ等)、G1 (記念競走) は明らかに開催されているはず。

### race_name は取れている
グレード判定の手がかりとなる開催タイトルは取得済み。例:
- "第２４回日本モーターボート選手会会長賞" (G1相当)
- "第２回スピードクイーンメモリアル" (G1相当)
- "ＢＴＳ鹿島開設１１周年記念　肥前鹿島干潟杯"
- "高塚清一記念　第８回　名人集合　マクール杯"

→ 仮にHTML側からgradeが取れなくても、race_name から推定する選択肢もあります。

---

## 3. 既存実装

### `src/collector.py:216` `_parse_race_grade()`

```python
def _parse_race_grade(soup: BeautifulSoup) -> str:
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
```

呼び出し元: `src/collector.py:431` (raceresult ページのパース時)

### 推測される原因 (要検証)
- **A.** raceresult ページの HTML構造が変わって `is-sg`/`is-g1` クラスが付かなくなった
- **B.** raceresult ページにはグレード情報が表示されておらず、出走表/番組表/月間スケジュールにのみある
- **C.** クラス名のパターンが古い (例: `is-sg` ではなく別名)

→ 実HTMLを1ページ取得して確認すべきポイント:
```
https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20251123&jcd=24&rno=12
(SG/G1開催と思われる日のレース)
```

---

## 4. 依頼内容

### Step 1: 原因特定
1. グレードが明確に SG/G1 であるレース (例: 2025年12月のグランプリ、2026年3月のクラシック等) を1つ選び、実HTMLを取得
2. raceresult ページに grade 情報があるか確認 → 無ければ別ページを探す
3. 出走表 (`racelist`)、月間スケジュール (`monthlyschedule`) を確認

### Step 2: 修正案検討 (どちらか/両方)
- **Plan A**: `_parse_race_grade()` のセレクタ修正で動かす
- **Plan B**: 別ページ (例: monthlyschedule) からグレード情報を取得して race_information に反映
- **Plan C**: race_name のキーワードマッチで暫定推定 (「ＳＧ」「Ｇ１」「Ｇ２」「Ｇ３」表記、または有名タイトルリスト)

### Step 3: 過去データ補完
- 既存62,000+レース全てに grade を埋め直す
- 再スクレイピングする場合は **1.5秒間隔ルール厳守**
- もし時間がかかるなら、まず race_name からの推定で暫定埋めし、後追いで正確版に置き換える方針もアリ

### Step 4: 進捗報告
完了後 / 進捗を本ファイルの末尾に追記し、`analysis/simulation_log.md` 検証セッションが grade ベースの仮説検証を再開できる状態にしてください。

---

## 5. なぜ grade が必要か

horse-race プロジェクトの教訓では「**グレードごとに市場の歪みが違う**」ことが判明しています:
- G1で 121.9% に達したオッズパターン戦略が、G2/G3 では崩れた
- 控除率は同じでも、賭ける層・分散・本命の信頼度がグレードで変わる

仮説 #001 / U-001 のオッズパターン戦略は **グレード別に切らないと過学習する** 可能性が高く、本格運用に進めるには grade 情報が必須です。

---

## 6. 環境セットアップ

handoff_hypothesis_testing.md と同じ。`.env` 内容も同じ。

---

## 7. 注意事項

### 既存収集パイプラインを止めない
2024年バックフィルが Turso に書き込み中です。collector を直接いじる場合、バックフィルが終わるまで待つか、別ブランチで作業してください。

### Turso 書き込みレート
過去データの一括埋め直しは1.5秒以上の間隔で。同時実行する場合も既存バックフィル+8並列 = 9並列を超えないこと。

### スキーマ変更不要
`race_information.race_grade` は既に TEXT カラムが存在。`UPDATE race_information SET race_grade = ? WHERE race_code = ?` で埋められます。

---

## 8. 完了の定義

- [ ] 原因が特定され、本ファイルにまとめられている
- [ ] collector が今後のレースで grade を正しく取得できる
- [ ] 既存レース (少なくとも 2025-2026 分) で grade が "一般" 以外も入っている
- [ ] 検証SQL: `SELECT race_grade, COUNT(*) FROM race_information GROUP BY race_grade;` で SG/G1/G2/G3 が出てくる
