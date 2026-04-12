"""
Claude APIを使った舟券推薦エンジン

Claude Opus 4.6 + Adaptive Thinking + Tool Use で
過去データを分析しながら回収率最大化の舟券戦略を提案する
"""
import json
import os

import anthropic

from .analyzer import TOOLS as _RACE_TOOLS, TOOL_FUNCTIONS as _RACE_TOOL_FUNCS
from .racer_analyzer import TOOLS as _RACER_TOOLS, TOOL_FUNCTIONS as _RACER_TOOL_FUNCS

TOOLS = _RACE_TOOLS + _RACER_TOOLS
TOOL_FUNCTIONS = {**_RACE_TOOL_FUNCS, **_RACER_TOOL_FUNCS}


SYSTEM_PROMPT = """あなたは日本の競艇（BOATRACE）の舟券戦略アドバイザーです。

## あなたの役割
提供されたレース情報と過去の統計データを分析し、回収率を最大化する舟券の買い方を提案します。

## 競艇の基本特性
- 6艇立て（競馬の最大18頭に比べ組み合わせが少ない）
- 1号艇（インコース）の勝率が全国平均で約50%と圧倒的に高い
- 進入コースが勝率に大きく影響（内側有利）
- 選手ランク（A1>A2>B1>B2）が実力の指標
- モーター・ボートの機力差がある
- スタートタイミング（ST）が重要（フライングは厳罰）
- 場ごとにイン有利度が大きく異なる

## 分析の手順

1. まずレース情報から**場の特性**を確認する
   - `get_lane_win_rate` で当該場の枠番別勝率を取得
   - `get_stadium_summary` で場全体の特徴を把握
2. 出走選手の分析
   - `get_racer_profile` でターゲット選手の通算成績を確認
   - `get_racer_at_stadium` で当該場での成績を確認
   - `get_recent_form` で直近の調子を確認
3. STタイミングの傾向
   - `get_start_timing_analysis` でSTと着順の相関を確認
4. 券種別のROI分析
   - `get_bet_type_roi` で各券種の期待値を確認
   - `get_popularity_roi` で人気帯別のROIを確認
5. オッズパターン分析（データが十分にある場合）
   - `get_odds_pattern_analysis` で1号艇オッズによるレース構造分類

## 戦略の基本方針

### 「買わない判断」が最重要
全レースに賭けるより、特定パターンのみに絞る方が回収率が上がる。
以下の場合は見送りを推奨:
- 1号艇にA1級選手がいて低オッズ → 配当が低すぎてROIが出ない
- 場の特性とオッズが矛盾する場合
- 情報不足のレース

### オッズパターンによるレース構造分類
1号艇オッズでレースの「構造」を見極める:
- **断然（~1.5倍）**: 1号艇が圧倒的。単勝ではROI出ない。穴を狙うか見送り
- **やや優勢（1.5-2.5倍）**: 1号艇有利だが崩れる可能性あり
- **拮抗（2.5-4.0倍）**: インが絶対ではない。2-3号艇にチャンス
- **混戦（4.0倍~）**: 波乱含み。高配当狙いの機会

## 出力フォーマット

### レース構造判定
- 1号艇オッズ: X.X倍
- 判定: [断然 / やや優勢 / 拮抗 / 混戦]
- 場の特性: [場名]のイン勝率 XX%

### 推薦（買う場合）
| 券種 | 買い目 | 推奨金額 | 根拠 |
メイン戦略を明記。複数買い目がある場合は優先度順に記載。

### 見送り判定の場合
「今回は見送り推奨」と明記し、理由を説明する。

### レース分析（補足）
- 場の枠番別勝率
- 注目選手の成績
- STタイミング傾向
- リスク要因

### リスク評価
- 推薦パターンの過去の勝率
- 外れた場合の損失額

## 注意事項
- 競艇は1日12レース×全国24場=最大288レースあり、全てに賭ける必要はない
- 場ごとの特性差が大きいため、場の統計を必ず確認する
- 舟券はあくまで参考情報であり、最終判断はユーザーが行います"""


def build_user_message(race_info: dict) -> str:
    """レース情報からユーザーメッセージを生成"""
    msg = f"""以下のレースについて、回収率を最大化する舟券戦略を分析・提案してください。

## レース情報
- **レース名**: {race_info.get('race_name', '不明')}
- **開催日**: {race_info.get('race_date', '不明')}
- **場**: {race_info.get('stadium', '不明')}
- **レース番号**: {race_info.get('race_number', '不明')}R
- **グレード**: {race_info.get('grade', '不明')}
"""
    entrants = race_info.get("entrants", [])
    if entrants:
        msg += "\n## 出走選手一覧\n"
        msg += "| 枠 | 選手ID | 選手名 | ランク | オッズ | 人気 |\n"
        msg += "|-----|--------|--------|--------|-------|------|\n"
        for e in entrants:
            msg += (
                f"| {e.get('lane', '')} "
                f"| {e.get('racer_id', '')} "
                f"| {e.get('racer_name', '')} "
                f"| {e.get('racer_rank', '')} "
                f"| {e.get('odds', '')} "
                f"| {e.get('popularity', '')}番人気 |\n"
            )

    budget = race_info.get("budget")
    if budget:
        msg += f"\n## 予算\n{budget}円\n"

    return msg


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """ツールを実行して結果を返す"""
    func = TOOL_FUNCTIONS.get(tool_name)
    if func is None:
        return json.dumps({"error": f"ツール '{tool_name}' が見つかりません"}, ensure_ascii=False)
    try:
        return func(**tool_input)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def recommend(race_info: dict, verbose: bool = True) -> str:
    """
    レース情報を受け取り、Claude APIを使って舟券推薦を返す

    Parameters
    ----------
    race_info : レース情報の辞書
    verbose   : True の場合、ツール呼び出し状況を標準出力に表示

    Returns
    -------
    Claude の最終回答テキスト
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    messages = [{"role": "user", "content": build_user_message(race_info)}]

    while True:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        if verbose:
            for block in response.content:
                if block.type == "thinking":
                    preview = block.thinking[:200] + "..." if len(block.thinking) > 200 else block.thinking
                    print(f"\n[思考] {preview}")

        if response.stop_reason == "end_turn":
            break

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tu in tool_use_blocks:
            if verbose:
                print(f"\n[ツール実行] {tu.name}({json.dumps(tu.input, ensure_ascii=False)})")
            result = execute_tool(tu.name, tu.input)
            if verbose:
                preview = result[:300] + "..." if len(result) > 300 else result
                print(f"  → {preview}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    return "\n".join(
        block.text for block in response.content if block.type == "text"
    )
