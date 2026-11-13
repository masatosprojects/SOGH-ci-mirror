# Work 夜間成果の独立実行・更新経路統合・操作デモ（2026-11-02）

Issue #55 / #75。初期基点 `38962d8`、最終同期 `5db1de0`（PR #91 / #92 統合後）。
**M1 は 2/8 verified（g4 / g8）、NOT ACCEPTED のまま。** 本PRは受け入れ台帳を変更しない。
Claude の実装を Work が読み、未変更の監査 harness を再実行した結果と、Work 自身が追加した試験を分ける。
Work の今回の変更は `SELF_VALIDATED`。Claude による独立レビューは別途必要。

**追記（2026-11-02）**：Claude PR95の独立レビュー（F1修正要求、F2a/F2b/F3推奨）を受領して修正した。修正点と31件の再試験結果は `FOLLOWUP_REVIEW.md`。修正後headの再レビューは別途必要。旧証拠JSONは前回実行の記録として保持する。

## 成果物の対応

| 要求 | 実体 | 状態 |
|---|---|---|
| A 現状監査 | `REVIEW.md` §1、`evidence/local-audit.json`、`input-manifest.json` | 原本5世代＋監査コピー5世代を読み取り専用検査 |
| B 夜間成果レビュー | `REVIEW.md` §2–4、凍結SQLチェックサム、独立実行記録 | コピー上の実行済み。本番・原典の意味照合は含まない |
| C 更新コード | `work-current-stage1.patch`、`preconditions.json`、`prepare_isolation.py` | 隔離コードのみ改修。既存Workルートは未変更 |
| D M1結合試験 | `evidence/claude_g4_report.json`、`claude_additive_report.json`、`review_tests/` | 使い捨て実コピーと合成負例。公式ゲート判定は未変更 |
| E 面接デモ | `demo/` | 既存Sandboxをimport。架空3ケース、文字のみ |
| F 受験報告フォーム | 同じ `demo/` の別タブ | 架空対象固定、同意3種類独立、保存・公開なし |
| G ロードマップ | `REVIEW.md` §7、`NEXT_SESSION.md` | 担当・依存関係付き |
| H ユーザー判断 | `REVIEW.md` §8 | 未承認事項を実行済みにしない |

## 更新コードの再現

PowerShell。`<WorkRoot>` は既存SOGHコード、`<NEW_DIR>` は**存在しない、元コードの外の使い捨て領域**を指定する。
生成するのはコードコピーだけで、DBを開かない。事前条件4ファイルの正規化SHAが違えば中止する。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -B -X utf8 research/inbox/work-night-integration/prepare_isolation.py --source-root '<WorkRoot>' --output '<NEW_DIR>'
$env:SOGH_PIPELINE_ROOT='<NEW_DIR>'
$env:SOGH_REVIEW_QA_ROOT=(Get-Location).Path
python -B -X utf8 -m pytest research/inbox/work-night-integration/review_tests/test_work_write_contract.py research/inbox/work-night-integration/review_tests/test_demo.py -q -p no:cacheprovider
```

既存Workテスト247件は、**コピーのディレクトリをカレントにして**実行する。
`SOGH_SOURCE_ROOT`（保存原典）、`SOGH_LEGACY_DB`（読取専用v02入力）、`SOGH_CLAUDE_ROOT`（このQA checkout）を明示する。
元Workルートをカレントにした試験は、元コードをimportし得るため修正版の証拠にしない。

実コピー検証は、容量を確認した後、下記の `<audit-v06>` / `<audit-v05>` を**監査コピーの入力**にして実行する。
出力先は新規の使い捨て領域。原本・監査コピーは変更しない。50根拠・13草案の現行JSONはローカルの既存受け渡しを使う。

```powershell
$env:SOGH_G4_PIPELINE='<NEW_DIR>'
$env:SOGH_G4_QA_ROOT=(Get-Location).Path
$env:SOGH_G4_VIEW='<local-current-active-state.json>'
$env:SOGH_G4_PREPARE='src.integration.g4_prepare:prepare'
python -B -X utf8 src/integration/real_copy_g4_audit.py --source '<audit-v06>' --older '<audit-v05>' --out '<NEW_G4_OUTPUT>'
python -B -X utf8 src/integration/real_copy_additive_audit.py --source '<audit-v06>' --older '<audit-v05>' --legacy-export research/inbox/work-updates-v2/samples/general/claude-compatible-export.json --out '<NEW_ADDITIVE_OUTPUT>'
```

## デモの起動

このリポジトリのルートで実行。既存ワーカーやタスクスケジューラとは接続しない。

```powershell
python -B -X utf8 research/inbox/work-night-integration/demo/server.py --sandbox-root sandbox --port 8766
```

ブラウザーで `http://127.0.0.1:8766` を開く。終了は起動した画面で Ctrl+C。
**実名・連絡先・実際の志望理由書を入力しない。架空データ限定。**
メモリ内最大4セッション、30分で失効。回答のログ・ファイル保存・外部AI・入試DB接続はない。
再起動後の練習再開は意図的にできない。端末やブラウザー自体による保存まで保証するものではない。

```powershell
python -B -X utf8 -m pytest research/inbox/work-night-integration/review_tests/test_demo.py -q -p no:cacheprovider
# 任意：既存のPlaywrightとEdgeがある環境のみ。インストール・ダウンロードは行わない。
python -B -X utf8 research/inbox/work-night-integration/review_tests/browser_smoke.py --output '<NEW_SCREENSHOT_DIR>'
```

スクリーンショットは架空画面だがローカル保存のみ。公式PDF・HTML原本、全文抽出、実DB、APIキー、CookieはこのPRに含まない。

## テストの読み方

- 現行Work baseline：247成功 / 失敗0 / skip0。
- 隔離修正版Work：247成功 / 失敗0 / skip0。baselineと合算しない。
- 新規Work試験：20成功 / 失敗0 / skip0（更新契約8、デモ12）。合成のみ、自己検証。
- 未変更Claudeの関連試験：88成功 / 失敗0 / skip0（初期master）。#91取り込み後、変更のあったSandbox＋デモを35件再試験し成功（重複を合算しない。Sandboxの新規1件を含む）。
- 使い捨て実コピー：g4 22 PASS / 0 FAIL / 0 known_limit、追加型20 PASS / 0 FAIL。監査の原典照合 `not_run` は成功に数えていない。
- ブラウザー：2シナリオ、JavaScriptエラー0、外部リクエスト0。人による入力所要時間・品質評価は `NOT_RUN`。

CIの標準ジョブはこのWork専用ディレクトリの新規20件やローカル実コピー監査を自動実行しない。
CI成功と上記ローカル実行を明確に分ける。CI接続・Workパッチ・UIの独立レビューはClaudeへ依頼する。
