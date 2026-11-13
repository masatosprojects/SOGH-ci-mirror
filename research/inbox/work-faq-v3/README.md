# Work PR42 復帰・FAQ正式更新の再検証

## 現在の状態

PR42のデータは保全し、新masterの確定QAへ再接続した。#48/#47はClaude PR49/50で解決済み。過去の契約待ちやCI失敗はhistory以下の当時の記録であり、現在の停止条件ではない。

データは50根拠13草案。新FAQ EV-U-61c185ec5771、親EV-U-467264a91b3e、5boolean T/F/F/T/T、6引用参照・一意な原文5箇所、ACの特定周期のみ。公表日不明はnull、取得日と混同しない。今回原本/実DB/旧納品/記事本文は変更していない。v06というファイル名は新スキーマ完成ではない。

## 復帰後の実測

- Work既存全219成功/失敗0/skip0を再実行。新しいW-03コピー安全性5件は別実行で成功（PR59）。FAQ配布のテストはpipelineで再実行する。
- a6c4474の同一QAで旧/新を公平比較: 生の意味反転78/83→82/83（95%の閾値を維持）。正例誤検出0。独自14負例は新データで12検出・2未検証として報告・黙った見逃し0。未検証は検出へ加算しない。言語列挙1件の生の見逃しと未知の言い換えへの限界は残る。
- 原典付きWork全件CLIは7ゲート合格。現在の意味未検証は20（旧報告18、先行Claude21という過去の数値を強制しない）。qa/resume-full-view.jsonの実測を使う。HTMLの独立意味監査とは別。
- 公式FAQをUTC 2026-11-01T09:53:47に一度再取得。今回は生SHA、正規化本文、AC節の6引用文、保存位置、条件契約すべて一致。保存原本と取得内容を混同しない。新観測はDB更新ではない。
- 5世代をSQLiteオンラインバックアップで複製し全行/整合性/FK/原本SHA不変を確認。v06コピーから読取専用再生成した50/13は納品ビューと完全一致。固定ClaudeコードをWorkが実行したDB-01〜12は全pass、DB-14/15 warn、原典比較not_run。Claudeの独立実行は未完了（PR59）。
- 最新b84d3a4のQAでv06の新コピーにロールバック→同日再承認→再実行0登録0改訂を実行し、履歴22→24、元コピー不変を確認。偽QA=trueでも未知義務追記を拒否し有効head不変。これは制御テンプレート境界であり独立意味検出へ加算しない。

## 統合と責任分担

最新masterのClaudeコード/契約/CI/進捗JSONと生成ボードはそのまま保全する。共有文書をClaudeと重複編集せず、PR旧版のWork追記はhistory/WORK_PROGRESS_PRE_RESUME.mdへ当時の記録として保全した。masterの共有文書と自動生成ボードは改変しない。

CI・最新統合作業ツリーの全テスト・回帰/全体ビュー/audit_handoffが合格し、原典/実DBの未実施を隠していないことを確認した後にReadyとする。**Ready後のClaude最終独立監査前にはマージしない。** 過去の先行監査の条件付き合格を最新headの最終合格へ流用しない。

## 再現

pipelineを作業ディレクトリにして `python -B -m pytest tests -q -p no:cacheprovider`。
リポジトリルートで `python -m src.regression.report --run-tests --fail-on-skip --out-dir <新規出力先>`、`python -m src.regression.fullview --require-view --out-dir <新規出力先>`、`python -m src.integration.audit_handoff research/inbox/work-faq-v3`。原典があるローカルでは --pdf-dir を別途指定する。原典なしCIのsource_pdfs/databaseはnot_run/skippedを維持する。

## 次の依存作業

W-02 stage実データ付与（案A、interview/fee_refundは[1]）は別の版・コピー上で行い旧記録を改名しない。W-04 G05の同一性/別名と一意制約はIssue55でWork方針を提案してから実装。実DBへのスキーマ変更/全面移行は禁止。W-03実コピーのClaude独立監査、G05合意、安全なコピー移行/障害復旧、新様式E2EがM1の残条件。

noteアクセス/下書き/公開、有料API、本番ワーカー/スケジューラ操作、ユーザー本人の承認イベント代理作成は行わない。PR58の公開承認契約は保全するが実操作やユーザー承認は作らない。**M1 NOT ACCEPTED**。
