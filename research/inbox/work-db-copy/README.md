# W-03 実DBコピーの現状監査（Work提出・独立判定待ち）

対象: Issue55 / P1-WP1.2、M1.g1〜g6/g8の監査入力。初回QAはa6c4474、今回の再計算QAはb84d3a41015570edb4ff1e8646b495222eaea7fb（db_auditに差分なし）。
これはスキーマと監査メタデータの納品であり、新規大学/記事exportではない。データhandoffの自動探索に載せるための架空記事・全体ビューは作らない。checksums.jsonに全ファイルのSHA/サイズを記録する。通常CIがこのメタデータや非公開DBを独立監査したとは扱わない。

## 実際に確認した対象

| コピー | 実ファイルの区分 | 表 | 基底事実 | 記事版 | 根拠改訂 | 記事改訂 |
|---|---|---:|---:|---:|---:|---:|
| v02 | Downloadsにある保全対象の旧DB |17|27|6|対象表なし|対象表なし|
| v03 | ローカル開発保存領域 |14|35|18|対象表なし|対象表なし|
| v04 | ローカル開発保存領域 |14|40|18|対象表なし|対象表なし|
| v05 | ローカル開発保存領域 |21|46|21|8|20|
| v06 | FAQ更新を保持する開発作業DB |21|46|21|9|22|

v06というファイル名はスキーマv0.6の完成を意味しない。user_version、schema_versions、全DDL/制約/索引/トリガーはdatabases/<識別名>/real_db_inventory.jsonとreal_db_schema.sqlに実測値を保存。本番として運用中のDBの指定は未確認。v0.2からの全面移行はしていない。

## コピーと保全

source mode=ro + query_only、読取トランザクションのSQLiteオンラインバックアップを使用。コピー取得時点の全表・全行の論理ハッシュが一致し、integrity_check=ok、foreign_key_check=0を全5ファイルで確認。取得前後の原本主ファイルSHAは不変。WAL/SHMの有無/ハッシュも記録した。原本に書き込むSQL・マイグレーションは実行していない。ヘッダーなどにより、オンラインコピーのバイトSHAが原本と同一になることは要求しない。

実コピーはGitの管理外の同一PCにのみ保存。秘匿化はしておらず、原本との全行同一性を維持する。コピーには保存原文ページ・公式資料内の連絡先メール・ローカルパスがあるのでGitHub送信不可。privacy_reportは値を出さず表/列/分類/件数だけを示す。パターン走査は全種類の個人情報の不存在の証明ではない。

## Claude独立監査（PR60）とF-1/F-4修正

初回head20cabceは、Claudeが同一PCの5コピーを独立に読み、メタデータ215検査・5コピーのSHA・全世代の監査判定の一致を確認。自前比較でもv05→v06の旧行変更/削除0、有効ビュー50/13を再計算した。判定PASS_WITH_WARNINGS。独立性はメタデータとコピーまで、原典と原本DBはnot_run。M1.g8のみverifiedとしたのはClaude側の判定で、Workは変更していない。

F-1: JSON内の二重バックスラッシュをuser_pathパターンが漏らしていた。区切りを1個以上とし、再計算でupdate_batches.qa_jsonのv05=13セル/v06=14セルを追加検出。秘密値は報告に含めない。コピー/原本を秘匿化のために書き換えていない。

F-4: バックアップ中は.sqlite.partialにだけ保存し、整合性/FK/全行同一性検査後に正式.sqlite名へ変更する。異常中断やFK不正では.partialを残し、正式ファイルを作らない。事前にpage_count×page_sizeと空き容量を検査するが、空き容量の競合まで保証したとはしない。故障の種類/段階を値なしの失敗レポートへ保存する。

コピーを新しいv2保存先へ実際に再取得し、5世代すべて初回とバイトSHAまで一致・原本SHA不変を確認した。旧コピーは保全。新しいコピー安全性8テストを再実行し8成功（JSON内パス、空き容量不足、途中障害、WAL、既存コピー保護等）。修正後headのClaude確認は別途必要。

## F-2：v03→v04の履歴断絶（failのまま）

Claudeの所見をWorkでも全共通表の行比較で再現した。v04をv03と比較したDB-09はfail。facts5行・article_versions6行が変更/置換、article_evidence24行・cycle_editions1行が失われている。詳細はqa/F2-history-diff.json。v04単体の整合性合格やv05→v06の保全を、この組の保全成功へ拡張しない。

当時の実行コマンド/直接の原因は現存コードと保存記録だけでは確定できていない。現在のコードにfacts/article_versionsを書き換えるSQLは見つからなかったが、当時も無かったという証明ではない。v03は別ファイルで現存し今回も保全した。旧文書の「旧11表保持」は測定したbaselineについての過去報告で、v03全行→v04全行の不変移行を保証できないため、その広い解釈を撤回する。

今回の修正で旧DBを書き換えて帳尻を合わせない。旧世代の別保存と行ハッシュを維持し、今後は実際の移行前後の全表対応/ID対応/不変比較を必須にする。既存世代の履歴を統合/復元する移行は、合意・独立試験・ユーザー許可が揃うまで実行しない。G-04/G-05も未解消。

## 監査の主体と結果

WorkがClaudeの確定コードを無変更で実行した結果。全5世代の単体監査はfail0。v06はv05のオンラインコピーをbaselineとしてDB-01〜12すべてpass（DB-09もpass）。DB-14/15はwarn（追記専用トリガー・検索索引不足）。原典比較はdb_auditの仕様上not_run。別にv04をv03と比較するとDB-09 failである。初回コピーへのClaude独立監査はPR60で完了、今回の修正headへの確認とは分ける。

v02の投稿0件はV02-05 not_run、旧コピーなしの各世代DB-09もnot_run。v03/v04には改訂/更新表がなく該当検査はnot_run。ok=trueは「全検査を実施済み」という意味ではない。

## Claudeが同一PCから独立に再現する手順

別環境でこのコピーが見えないときはnot_accessible/not_runとし、GitHubからコピーを取得できるとは仮定しない。原本を停止・変更する必要はない。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$copies = Join-Path $env:USERPROFILE 'SOGHRuntime/AuditCopies/work-resume-m1-v2'
Test-Path (Join-Path $copies 'v06.sqlite')
# 確定QAを別保存先へ展開してから、そのQAルートで実行する。
python -X utf8 -m src.integration.db_audit "$copies/v06.sqlite" --baseline "$copies/v05.sqlite" --target-kind copied_real_db --expect-sha256 a8e48b5b16239368e9b5c05aad1dbeb692a657f28dab909bf3c99fff41539578 --json-out <新規出力先>/v06.json
```

全5ファイルのSHAとサイズは各inventoryのcopyに記録。実行者・QAコミット・出力先・実行時のcopy SHAを記録し、Workの保存したレポートを結果として流用せず再計算する。QAが更新されている場合は固定版との差を別記録する。

コピー取得ツールの再現（新しい出力先を必ず使用）と負例:

```powershell
# reproductionを作業ディレクトリにし、pytestがあるPythonで実行
python -B -m pytest tests -q -p no:cacheprovider
python scripts/inventory_real_databases.py --runtime <実DB保存領域> --v02 <旧v02の明示パス> --copies <存在しないコピー保存先> --output <存在しないメタデータ出力先>
```

負例/安全性は修正後8テスト。実行した件数はqa/work-tests.jsonへ記録する。初回の5成功/既存Work219成功も当時の結果として残し、修正後の全体テストと混同しない。

## 未実施と次の依存作業

修正headについてのClaude確認、原典付き独立監査、F-2履歴断絶の扱い、スキーマ改善、stageの正式有効化、G-05別名/ID方針の合意、実コピーでの新移行/障害復旧、新資料様式E2Eが残る。Claude PR60でM1.g8だけがverifiedとなりM1は1/8。受け入れ判定はClaude管理のボードで行い、Workからacceptedへ変更しない。

公開承認イベント・編集確認イベントは作っていない。ユーザーの確定方針（本人が編集確認・最終公開判断、明示許可後に下書き、その表示確認後に最終公開承認）を適用する。旧masterの「編集担当/順序未定」は最新ユーザー指示に優先しない。Claude側で該当文書が編集中のため、Workは共有文書を重複修正しない。

**M1 NOT ACCEPTED**。本納品は受け入れを判定するための実入力と再現証拠であり、M1完成の宣言ではない。
