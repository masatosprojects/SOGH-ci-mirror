# SOGH 第2段階：継続収集とQA付き改訂

Work担当。Issue #26 / #17。収集・DB更新・草案生成のみ。Claudeの `src/`・`tests/`・本番ボット・夜間ワーカー・タスクスケジューラを変更しない。

## 実装

- `monitor.py`：URL別SQLite状態、初回/不変/変更/未到来/失敗、最終試行/成功、SHA-256、取得日時、再試行上限、失敗バックオフ、robots、同一URL重複防止。壊れたPDF/文字コードは失敗として保存し、他URLを続ける。失敗した最新版を旧成功版で代用して評価しない。
- `ProcessLock`：WindowsのOSロック。プロセス異常終了で自動解放。CLIの生存期間全体をロックし、待機中の二重起動も拒否。STOPは取得・分析の境界と待機中に確認する。再起動時のSTOP解除もロック取得後に限る。
- ClaudeのSourceSnapshot/変更差分/影響分析へ既存CLIで接続。HTMLのバイトのみの変化と可視本文の変更を区別する。未分析チェックは異常終了後も再開可能。
- `supplements.py`：確認済みURL・ハッシュ・一意な本文位置・ページ/節・対象年度/方式を照合。HTMLをPDFと偽らない。公表日不明はnull。未登録/提案中fact_key、未確認新版は別保留とし、有効事実に入れない。
- `revisions.py`：旧版を残す追加テーブル。有効根拠/記事の頭ポインタ、親根拠、バッチ、QA結果、イベント履歴。QAの対象記事ハッシュ・入力ハッシュ・登録簿ハッシュ・更新前状態を照合後、同一トランザクションで有効化する。不合格/中断候補は有効化しない。後続更新を捨てるロールバックも拒否。
- `apply_updates.py`：入試サイクル単位の原子的QAバッチ。複数サイクル全体が1トランザクションであるとは扱わず、各結果を必ず報告する。
- `generic.py`：新方式は候補DBでPDF抽出→出典付き事実→記事入力→3草案→Claude QA→独立PDF/値照合。合格後に旧行不変・同時更新なしを再確認して追加差分だけ反映する。失敗候補は本体へ反映しない。
- `export_active.py`：承認済み頭ポインタだけで現在の全体ビューを構築する。旧事実・旧記事自体は削除しない。
- 全体ビューはDBの単一読取トランザクションから構築し、元JSONの値・年度/方式・原記事本文がnative DBと違う場合は出力しない。

## 現時点の受入状況

Issue #34 はPR #37で解決し、登録簿1.5.1（475a1f5）を固定して検証した。小作文は既存statement_lengthに含まれ、自然な面接評価文も正当と確定。根拠の意味は変えていない。新一般選抜6根拠3草案、全体50根拠13草案の正例QA・保存した原典照合は合格。クリーンv0.4コピーへ40→46根拠/旧18→21記事の取り込み、既存6記事の新QA再承認を実行した。

全体ビューの生の回帰能力検査は、反転78/83で既存95%閾値に届かず不合格となる。FAQの下線例外4件と同段落に英語が残る1件の検出漏れであり、正例記事の不合格とは区別する。CLIはこの不足を隠さずexit 1/未検証項目として残す。契約追加はIssue #39、CI接続は#36。既存のQA・閾値は変更していない。これらを全体回帰合格や意味の完全検証とは報告しない。原典の最新版網羅・公開許可も別である。

## 導入・試験（本番タスク登録なし）

配布物の `pipeline` ディレクトリで Python 3.11以上を使用。依存は `pytest`, `pymupdf`, `pypdf`, `jsonschema` とClaudeリポジトリの `requirements.txt`。有料AI呼び出しは不要。

```powershell
python -B -m pytest tests/test_national.py tests/test_updates.py tests/test_import_activation.py -q -p no:cacheprovider
```

共同開発リポジトリを別途参照する。再現性が必要なら `scripts/pin_claude_qa.py --repo <共同開発チェックアウト> --commit <40桁SHA> --output <未作成のQA保存先>` を使う。これは既存ブランチを切り替えず、コミット済みファイルを別ディレクトリへ読み出す。QA保存先を手で編集しない。

## 監視の手動運用

初期監視間隔は1時間。`monitor.example.json` は主要4資料、`monitor.all.json` は27資料。状態ディレクトリはDBとは分離する。

```powershell
# 1回のみ。監査連携には全対象設定と、その設定でカバーする全体ビューを指定する。
./start_monitor.ps1 -Config ./config/monitor.all.json -State "$env:USERPROFILE/SOGHRuntime/OfficialMonitor" -Export <active-state.jsonの絶対パス> -Collab <QAディレクトリの絶対パス>
# 継続実行は運用開始の判断後にのみ -Loop を加える。
./stop_monitor.ps1 -State "$env:USERPROFILE/SOGHRuntime/OfficialMonitor"
```

ログ/PIDだけで成功としない。`State/reports/*.json` のsuccess、失敗URL、versioning.unassessed_evidence、requires_reviewを確認する。初回は既存事実との比較対象がなく、安全に継続できるとは限らない。`requires_review=true` は調査待ちであり自動登録しない。STOPは強制終了しないため、実行中の最大30秒のHTTP取得と上限付き分析の終了まで待つ。

CLI直接実行も可能：`python -B -m admissions_pipeline.monitor --config <設定> --state <状態> --export <全体ビュー> --collab <QA保存先>`。通常は期限到来分だけ取得する。`--force` は明示的な再監査用で、定期実行では使わない。`--loop` も手動運用のみ。Windowsスリープ中は動作しない。運用開始する場合は電源接続時のスリープ設定を別途決定する。今回は電源設定・本番登録を変更していない。

## 更新と復元

v0.4は読み取り専用の原本として維持し、新しいv0.5作業DBへコピーする。旧v0.2ファイルも使用しない。DB、原本PDF、全文、SourceSnapshot、バックアップはローカル専用。

```powershell
python -B scripts/apply_updates.py --specs config/updates.with-correction.json --monitor-root <監視状態> --base-export <元記事と根拠のJSON> --base-db <v0.4原本> --work-db <v0.5作業DB> --qa-root <QA保存先> --output <未作成の結果ディレクトリ> --as-of 2026-11-01
python -B scripts/export_active.py --database <v0.5作業DB> --base-export <元記事と根拠のJSON> --output <active-state.json>
```

この実行例は今回確認した版の設定であり、将来版を自動承認しない。現設定の一般選抜訂正は既存 `EV-G27-01-e1137e` を親に持つため、その開発データがある作業DB専用。新規導入は一般選抜の抽出プロファイルを使う。未確認SHAや保留があればbatch-reportは不成功となる。

同じ根拠・同じ記事の再実行は新規登録0/改訂0。テンプレート改訂だけを行う場合に限り `--refresh-articles` を明示する。例の基準日を現在の日付に変える際は期限の意味も再確認する。

更新前バックアップと不合格候補は結果ディレクトリへ保存。戻す場合は書き込みプロセスを止め、別コピーで整合性検査をしてから切り替える。`RevisionStore.rollback_batch(batch_id)` は直近の有効状態に一致する承認バッチだけを戻す。物理的な旧行・記事履歴は削除しない。クラッシュ候補は次回ロック取得後にinterruptedとなり、再抽出・再QAする。

## 全体ビューとCIの検査範囲

`samples/current/active-state.json` は既存IDを再利用する現在の50根拠・13草案の全体ビュー。旧納品とのID衝突を避けるため、新規納品探索用ファイル名にしない。これは検査除外を隠すためではなく、旧納品と別物として二重登録しないためである。全件の原典・値・記事・変異検査はローカル報告 `qa/` に保存する。

`samples/general/claude-compatible-export.json` は新一般選抜の独立6根拠・3草案。既存CIが自動探索・回帰検査する。既存CIは `pipeline/tests` を実行しないため、Workの試験結果とCI結果は区別する。ClaudeのQAコードをこの配布物へ複製・改変しない。

全文や原本を渡さないため、GitHub上の原典PDF照合は未実施/skipとして明示される。ローカルの実原本照合結果と混同しない。

## 残る制約

設定にない新URLの全自動発見、OCR・複雑な表の完全自動解釈、新版の意味的な自動承認、全大学網羅は未完了。対象URL・根拠アンカー・適用範囲は人間/Workの確認が必要。現在は未公開テンプレート草案で、AI APIもnote投稿も行っていない。監視の常時稼働は開始していない。


## PR #33 継続改善：全体ビューの同条件回帰

```powershell
python -B scripts/verify_full_view.py --view outputs/updates-v2/current-export.json --qa-root inputs/qa/<確定SHA> --prior-inbox inputs/qa/<確定SHA>/research/inbox --reference-date 2026-11-01 --scope full --bodies outputs/updates-v2/monitor/bodies --output reports/updates-v2/full-view-<新規名>
```

`--previous <前回report.json>` で記事別の内容/判定/出典メタデータ/未検証項目と条件差を記録。QAコミット、登録簿/入力ハッシュ、Python/依存版、基準日を固定する。元IDは変更しない。同じ内容の旧納品ID再利用は許容し、同じIDで値/対象/出典/証拠または本文が違えば失敗。JSON重複キーと全体ビュー内の記事重複も拒否する。未完了/エラー状態はstate.jsonに保存し、完了判定にしない。

原本を持たないGitHub CIは `--scope export --execution-origin github-ci --prior-inbox research/inbox` とし、raw_sourcesはnot_runとして成功数に含めない。CI接続はClaude担当へIssue #36で依頼済み。Workは既存ワークフロー/回帰コードを変更していない。意味検証の未対応17項目（改善前の測定）も原典照合の成功と別に報告する。

### 監視・DB負例の追加

- ローカルHTTPサーバーをTCP転送先に使い、公式URL/HTTPS/redirect許可判定は本体のまま試験。403/404は再試行しない、429/500/タイムアウト/切断は上限付き。壊れた圧縮/長さ不足/UTF-8/PDFは前回の正常なsnapshotを維持する。
- PDFの修復読み込みで途中ファイルを正常扱いしない。HTTP本文長、PDF末尾、暗号化/修復/ページ有無を検査する。未知の形式は確認待ちにする。
- URL移転の同一本文も旧snapshotを残して新URLの観測を保存する。移転による版の継承は、設定で `supersedes_sha256` を確認して明示した場合に限る。新URLの初回取得と既知URLの更新を混同しない。
- `scripts/check_monitor_chain.py --qa-root <QA> --output <新規>` は通信なしで実Claudeのsnapshot→diff→影響記事を検査する。
- `scripts/check_revision_copy.py --database <v0.5作業DB> --view <全体ビュー> --qa-root <QA> --output <新規>` は新しいDBコピーに16→999999を故障注入し、実Claudeの引用値検査で拒否・頭ポインタ不変を確認する。本体DBは書かない。
- 有効化直前に本文/宣言引用IDの一致、引用の実在/サイクル/年度/方式を再確認し、記事QAのBooleanだけで通さない。記事とデータが同じ誤数値でも、出典引用内に値がない場合は改訂パイプラインの追加ゲートで拒否する。

### 新潟書類記事の差別化候補

`scripts/compare_document_drafts.py` は同じ募集要項から、共通テスト要否・面接の日時/書類評価・募集人数の方式差と、共通する郵送条件を分けた候補を生成する。一般助言/未確認事項も分離。主DB/全体50根拠13草案は変更しない。全文SequenceMatcherの類似度は98.25%→91.81%で、以前のClaudeの87%とは指標が異なる。類似度だけを合否にせず、依然共通部分が多い制約を残す。候補は別途QAし、今回の13草案の受入と混同しない。
