# Work → Claude：DB v0.2・原典照合・E2E成果物の受け渡し

Issue #1（Work資料提供）への提出、Issue #2（Claude実DB QA）の入力です。
変更範囲はこの `research/inbox/work-db-v02-20261101/` だけです。
Claude担当の `src/`、`tests/`、`reports/`、CI設定は変更していません。

## 含まれるデータ

- `data/admission_media_v0_2.sqlite.gz`：受領DBの独立バックアップをgzip圧縮したコピー。
- `legacy-v02-files/`：受領ZIPのスキーマ、元の6入力JSON・6草案・短い出典要約。
- `schema-inventory.json`：17テーブルの列、型、主キー、件数。
- `samples/claude-compatible-export.json`：原本版から抽出した30事実と4草案。既存の検証ゲート・記事QA形式に適合。
- `current-drafts/`：筑波AC・慶應SFC AOの制度概要・面接記事、計4本の未公開草案。
- `qa/`：読み取り専用DB QA、旧27事実の原典照合、新E2EとClaude QAの結果。
- `pipeline/`：Work側の再現用Pythonコードと19件の検証テスト。既存QAをサブプロセスで呼ぶ。
- `privacy-review.json`：共有前の検査結果。体験情報・個人別の応募データ・公開履歴は0件。

公式PDF原本と全文抽出ページはGitHubへ含めていません。
`source_extracts/*.txt` は要約であり、PDF原本ではありません。
DBの `source_snapshots.content_sha256` も要約ファイルのハッシュです。PDFハッシュに流用しないでください。
旧 `fact_claims.review_status='verified'` は受領当時の値を保存しただけで、新たな原典照合の証明ではありません。

## DBコピーを展開してPhase BのQAを実行

リポジトリ直下で実行します。コピーは一時領域へ展開し、元データへ書き込みません。

```powershell
$handoff = Join-Path $PWD 'research/inbox/work-db-v02-20261101'
$qaCopy = Join-Path $env:TEMP ('sogh-v02-qa-' + [guid]::NewGuid().ToString('N') + '.sqlite')
python -c 'import gzip,sys; from pathlib import Path; Path(sys.argv[2]).write_bytes(gzip.decompress(Path(sys.argv[1]).read_bytes()))' (Join-Path $handoff 'data/admission_media_v0_2.sqlite.gz') $qaCopy
python -m src.db_qa.sqlite_integrity $qaCopy --json-out (Join-Path $env:TEMP 'sogh-v02-db-qa.json')
python -m src.integration.validate_export (Join-Path $handoff 'samples/claude-compatible-export.json')
python -m src.run_qa_suite --articles-json (Join-Path $handoff 'samples/claude-compatible-export.json')
```

展開後のハッシュは `manifest.json` の `gzip_uncompressed_database_sha256` と照合できます。
バックアップ／復元の試験は `--backup-to` に別の新規パスを指定してください。

## 旧DBの構造と新処理への対応

大学 → 組織 → 方式 → `admission_cycles` → `selection_stages` → `fact_claims` の構造です。
各事実は `fact_evidence` から `source_snapshots` と `source_documents` を参照します。
記事は `article_plans` → `article_versions` → `article_version_facts` で根拠を逆引きします。

| 旧フィールド | 意味と注意 |
|---|---|
| `entry_year` | 入学年度。試験実施年と区別する |
| `field_key` | 事実の種類（人数・出願期間・面接日等） |
| `value_json` | 型付きの値。出願期間の開始と終了、単位、範囲などを保持 |
| `basis` | 公式・体験等の区別。原本を保存したという意味ではない |
| `review_status` | 旧システムの確認ラベル。今回の照合結果とは別 |
| `locator` | 旧PDFページ・章節。原典で再照合する |
| `source_snapshots.media_type` | 旧2件はテキスト要約。原本PDFではない |

今回の別DB v0.3では旧17テーブルの121行を `legacy_records` に不変のJSONとして保持し、
27事実を `legacy_fact_links` から新しい原本付きの `facts` へ結び付けています。
元のDBは変更していません。新しい原典照合は20件が一致、7件は一致した上で注記・条件を追加、矛盾0件です。
慶應の旧サイクルの対象は2027年4月入学として維持しています。新処理が扱う4月／9月の共通条件へ結び付けても、旧サイクルの対象を拡張しません。

重要な範囲は明示しています。

- 慶應の150名は年度内AO合計で、夏秋AO単独の定員は不明として保持。
- 慶應の30分は面接の実施時間枠。実際の質疑時間へ置き換えない。
- 筑波は学類別人数・面接日を取得し、他学類から流用しない。
- 国内消印と海外必着、システム休止、資格条件のOR／ANDを区別。
- 旧6草案は保存資料として維持。新4草案の検査結果を旧草案の合格と読み替えない。

## 再現用E2E

`pipeline/` を作業場所とし、保存した2件の原本PDFをSHA-256名で置いたフォルダーを指定します。
正確なURLとハッシュは `pipeline/admissions_pipeline/extract.py` にあります。
原本の版が変われば処理は停止し、再監査を要求します。

```powershell
# pipeline/ へ移動し、必要な依存関係を導入した環境で実行
python -m admissions_pipeline --source-root '<公式PDFの保存先>' --state-dir '<同期外の新規作業フォルダー>' --output-root '<成果物保存先>' --collab-root '<SOGH-collabのルート>' --legacy-db '<展開したDBコピー>'
```

テスト時は `SOGH_SOURCE_ROOT`、`SOGH_LEGACY_DB`、`SOGH_CLAUDE_ROOT` を指定し、
`python -m pytest tests/test_admissions_e2e.py -q` を実行します。
原本がない場合はテストがskipされます。skipを成功したE2Eとして報告しないでください。
現在の既存CIが実行するのはClaude側の76件であり、このinbox内のWorkテストは別途実行が必要です。

## 確認済みと未確認の境界

Work側で19件の新テストと実データE2Eを実行しました。既存Claude側の76件も独立に実行しました。
PDFの版・原文引用・値・年度・対象範囲をプログラムと目視で照合しましたが、
更新告知・訂正の網羅的な監査と公開承認は別工程です。QA成功は公開許可ではありません。
AI API・有料処理・note投稿は実行していません。

DB QAの警告1件は `fact_evidence` の同じ原文位置を複数事実が共有する関係です。
同じ事実の重複とは限らないため、警告を削除するためのデータ改変はしていません。
