# 回帰テストの報告

- 判定: **成功**
- 生成: 2026-11-01T03:45:40+00:00（commit c3af310）
- fact_key 登録簿: 1.1.0

## テスト件数

| 合計 | 成功 | 失敗 | エラー | **skip** |
|---|---|---|---|---|
| 313 | 313 | 0 | 0 | **0** |

## 受け渡しごとの検査

| export | 事実 | 記事 | ゲート | 登録簿エラー/警告 | 変異検出（本文／引用ID／全体） | 版管理 | 結果 |
|---|---|---|---|---|---|---|---|
| `work-db-v02-20261101/samples/claude-compatible-export.json` | 30 | 4 | 30/30 | 0/0 | 139/141・162/164・301/317 | 30事実 | ✅ |
| `work-national-v1/samples/humanities/claude-compatible-export.json` | 5 | 3 | 5/5 | 0/0 | 33/33・90/95・123/137 | 5事実 | ✅ |
| `work-national-v1/samples/law/claude-compatible-export.json` | 5 | 3 | 5/5 | 0/0 | 35/35・83/85・118/129 | 5事実 | ✅ |

警告（失敗ではない）:

- `work-db-v02-20261101/samples/claude-compatible-export.json`: mutation: as-of date edits detected 0/12 (Issue #11)
- `work-national-v1/samples/humanities/claude-compatible-export.json`: mutation: as-of date edits detected 0/9 (Issue #11)
- `work-national-v1/samples/law/claude-compatible-export.json`: mutation: as-of date edits detected 0/9 (Issue #11)

## 受け渡しをまたいだ検査

- 全体: 3 export・40 事実・10 記事。結果: **成功**（事実IDの衝突なし、他の受け渡しを混ぜても各記事の結果は不変）
- 警告: 1 near-duplicate draft pair(s) across exports: niigata-humanities-recommendation-II-2027:documents:b23ea2aa7d4fbcf6 and niigata-law-recommendation-I-2027:documents:1085376afccdcc39 are 87% similar

## ベースライン（過去の結果が変わっていないか）

- 変更なし: 3 件　／　変更あり: **0** 件　／　ベースライン未登録の新しい export: 0 件

## 独立監査（`audit_handoff`、公式PDFなし）

| 受け渡し | 失敗 | 要確認 | skip（検査できていない） |
|---|---|---|---|
| `work-db-v02-20261101` | - | reconciliation | source_pdfs |
| `work-national-v1` | - | - | database, reconciliation, source_pdfs |
