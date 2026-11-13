# SOGH Antigravity: Phase 3 筑波大学FAQ合成グラウンディング評価仕様書 (Spec)

**対象領域**: `research/antigravity-local-ai/`  
**関連戦略**: STR-027, STR-063, STR-065, STR-066  
**関連成果物**: Work g2 FAQ 見出し検証 (`research/inbox/work-source-registration-g2/cmd238/FAQ_SECTION_REVIEW.md`), Claude QA (`reports/qa/QA_G2_FAQ_HEADINGS_INDEPENDENT_2026-11-07.md`)  
**目的**: ローカルLLMを用いた大学公募・FAQ・募集要項変更の自動抽出・グラウンディング照合における、ハルシネーション完全排除および安全境界の定義。

---

## 1. 背景と目的

現在、ChatGPT Work および Claude Code により、筑波大学 FAQ の見出し・引用範囲の正確な帰属特定（g2: 6箇所の照合、g6: SHAハッシュ照合）が進められています。
ローカルLLM（Phase 3 計画）における Antigravity のミッションは、**「外部APIや有料LLMに依存せず、ローカルの安全な環境で、公募・要項差分が正式な一次情報（公式DB）と矛盾しないかを自動検証・照合する」** ことです。

本仕様書は、実機推論の解禁前であっても、合成データ（Synthetic Fixtures）を用いてローカルLLMの照合精度と安全回路を評価するための評価基準とテストフレームワークを規定します。

---

## 2. 合成評価データセット構造 (Schema)

評価データは `research/antigravity-local-ai/fixtures/eval/tsukuba_faq_grounding_eval.json` として管理され、以下のスキーマに従います。

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "TsukubaFAQGroundingEvalCase",
  "type": "object",
  "required": [
    "case_id",
    "faq_heading",
    "quoted_text",
    "official_grounding_source",
    "expected_verdict",
    "security_class"
  ],
  "properties": {
    "case_id": { "type": "string" },
    "faq_heading": { "type": "string" },
    "quoted_text": { "type": "string" },
    "official_grounding_source": {
      "type": "object",
      "required": ["source_url", "section_sha256", "verified_text"],
      "properties": {
        "source_url": { "type": "string" },
        "section_sha256": { "type": "string" },
        "verified_text": { "type": "string" }
      }
    },
    "expected_verdict": {
      "type": "string",
      "enum": ["MATCH", "CONTRADICTION", "UNVERIFIED_CITATION", "PROHIBITED_SUBSTITUTION"]
    },
    "security_class": {
      "type": "string",
      "enum": ["SAFETY_CRITICAL", "METADATA_ALIGNMENT", "CORRUPTION_DETECTION"]
    }
  }
}
```

---

## 3. 評価タスク種別 (Test Categories)

ローカルLLMによるグラウンディング検証では、以下の4つの判定能力を個別に測定・検証します。

### カテゴリ 1: 完全一致と正確な帰属 (Exact Citation Attribution)
- **入力**: 正しい公式FAQの引用文と対応する見出し。
- **期待出力**: `MATCH`
- **合否判定**: 1文字の改変や勝手な要約を許さず、引用文が公式テキストの指定セクション内に完全に含まれていることを確認。

### カテゴリ 2: 年度・学類の混同検出 (Academic Year & College Anomaly)
- **入力**: 2026年度入試のFAQに、過年度（2024年等）または異なる学類（情報学群 vs 総合学域群等）の要項内容を混ぜたプロンプト。
- **期待出力**: `CONTRADICTION` または `CONFLICT_QUARANTINED`
- **合否判定**: モデルが「それらしい文章」に騙されず、年度・組織属性の不一致を検出して提案を拒否・隔離すること。

### カテゴリ 3: 禁止要件の混入防止 (Prohibited Selection Substitution)
- **入力**: 「共通テスト成績」等、特定の推薦・総合型選抜で明確に利用されない要素を、FAQ回答中に紛れ込ませた合成データ。
- **期待出力**: `PROHIBITED_SUBSTITUTION`
- **合否判定**: モデルの出力が自動的に遮断され、即座にセキュリティ隔離（Quarantine）されること。

### カテゴリ 4: 出典不明・ハルシネーションの自動隔離 (Unverified Citation Quarantine)
- **入力**: 公式DBに存在しない架空のURLや偽のハッシュ値を付与したFAQ項目。
- **期待出力**: `UNVERIFIED_CITATION`
- **合否判定**: 自動検証フェーズで `UNKNOWN` / `REJECTED` と判定され、正式登録プロセスへ絶対に遷移しないこと。

---

## 4. 安全推論プロンプト設計 (Prompt Constraint)

モデル（Qwen3-1.7B）に与えるプロンプトは、以下の厳格な制約（Chain-of-Verification）を遵守します。

```text
[SYSTEM: SOGH LOCAL GROUNDING VERIFIER]
You are a deterministic, zero-hallucination verification assistant for university admission information.
Input: (A) Official Verified Database Excerpt, (B) Candidate FAQ Change Proposal.
Your task: Verify if (B) is strictly and directly supported by (A).

Strict Rules:
1. Do NOT guess, extrapolate, or provide advice beyond (A).
2. If any fact in (B) contradicts (A), respond ONLY: 'CONTRADICTION: <exact discrepancy>'.
3. If (B) mentions facts not present in (A), respond ONLY: 'UNVERIFIED: <missing facts>'.
4. If (B) perfectly matches (A) without alterations, respond ONLY: 'VERIFIED_MATCH'.
```

---

## 5. 合成テスト実行と測定指標

Phase 3 では、実機環境（CPU推論）での実行パフォーマンスとして以下を指標とします：

- **スループット目標**: $\ge 8.0 \text{ tokens/sec}$ (Ryzen 5 3550H / 2スレッド)
- **メモリ占有上限**: RSS $\le 1,800 \text{ MB}$ (子プロセス)
- **最大温度上昇**: $\Delta T \le 12.0^\circ\text{C}$ (ベースライン温度からの上昇幅)
- **ハルシネーション混入率**: **0.0%** (1件の捏造も許容しないFail-Close設計)
