# ARCHITECTURE.md — システム構造

## 全体像

SOGH事業は、大学入試情報を収集・DB化し、note記事として配信するシステム群で構成される。
本リポジトリ (`SOGH-collab`) は、既存の `SOGH`（ChatGPT Work担当）とは独立したディレクトリで、
Claude Code が担当する QA・検証・品質保証モジュール群を実装する場所である。

```
SOGH/              ← 既存（ChatGPT Work担当・読み取り専用で参照）
  ├─ (夜間ワーカー、DB本体、noteボット、モデルルーター 等)

SOGH-collab/        ← 本リポジトリ（Claude Code が独立実装）
  ├─ AGENTS.md
  ├─ CLAUDE.md
  ├─ docs/
  ├─ research/inbox/   ← Workからの情報受信
  ├─ research/outbox/  ← Workへ渡す成果物
  ├─ src/               ← 独立実装（検証モジュール等）
  ├─ tests/
  └─ reports/           ← 検証結果レポート
```

## Claude Code 側コンポーネント（計画）

- `src/db_qa/` — 既存DBの独立コピーに対する整合性検査（Phase B）
- `src/verify/` — 公式情報検証モジュール：日付/URL/PDFハッシュ/募集人数/記事整合性/JSON Schema（Phase C）
- `src/article_qa/` — 記事品質自動検査：数値根拠、年度違い、出典欠落、重複、テンプレ反復、過度な断定（Phase D）
- `src/integration/` — Work成果物受け入れ設計：インポート形式、DB移行、差分検査、ロールバック（Phase E、設計のみ先行）

## データフロー（想定）

1. 既存DB（読み取り専用） → コピー作成 → `src/db_qa/` で整合性検査 → `reports/` にレポート出力
2. 記事草稿 or 公開済み記事 → `src/verify/` + `src/article_qa/` → 根拠ID・数値・年度の整合性チェック → レポート
3. 検証結果は PR として提示し、適用判断は人間 or Work側に委ねる（本リポジトリから本番DB・本番ボットへの直接書き込みは行わない）

## 技術選定方針

- 形式的・定型処理: Python（標準ライブラリ + sqlite3 + jsonschema 等、軽量な依存のみ）
- スキーマ検証: JSON Schema (Draft 2020-12 相当)
- テスト: `pytest`
