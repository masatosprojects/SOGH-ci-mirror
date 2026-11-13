# 全国展開 第1段階（Work / Issue #22）

## 実装と実測

新しい方式は JSON プロファイルで追加する。新潟大学法学部・学校推薦型選抜Ⅰ型と人文学部・Ⅱ型を、同じ Python コードで処理した。各5事実、各3草案（概要・書類準備・面接準備）。共通テストを免除するⅠ型と課すⅡ型を分離し、表の数値・日程はページ画像でも確認した。

既存2方式30事実に追加し、v0.4作業DBは3大学4方式40事実。新規6草案を含む最新10草案が対象。DB中の全18記事版には以前のテンプレート版も含まれるため、最新草案数と混同しない。

## モジュール

- `admissions_pipeline/collector.py`：公式ホスト制限、robots、待ち時間、同一ホストのみのリダイレクト、容量制限、gzip転送復号、内容ハッシュ保存、取得履歴SQLite、訂正候補リンク。
- `admissions_pipeline/profiles.py`：JSON設定、版ハッシュ・表紙・一意アンカー・注記照合。整数と和暦日付は捕捉結果から変換。未知キー・欠落・曖昧一致・暗号化・本文なしは停止。OCRの推測補完は行わない。
- `admissions_pipeline/dimensions.py`：追加テーブルによる区分・入学年・試験実施年・入学月・募集期・学部学科スコープ・版/設定履歴。設定JSONも保存する。
- `admissions_pipeline/generic.py`：原本再抽出との完全比較→既存SQLite→入力JSON→用途別テンプレート→既存Claude QA。事実と編集上の助言を明示して区別。公開フラグは常にfalse。
- `scripts/check_collected_versions.py`：合意済み `docs/VERSIONING.md`（Claude PR #23）を使用。差分・影響分析はClaude実装を呼び、重複実装しない。

## 実行

Python 3.12、`jsonschema`、`pytest`、実PDF処理には `PyMuPDF` が必要。独立監査の第2抽出器として `pypdf` も使用した。

SOGHルート（受け渡しパッケージでは `pipeline/`）で:

```powershell
python -X utf8 scripts/audit_official_sites.py --config config/official_audit.json --output outputs/official-audit
python -X utf8 scripts/audit_official_sites.py --config config/official_audit_extra.json --output outputs/official-audit
python -X utf8 -m admissions_pipeline.generic --profile config/profiles/niigata-law-recommendation-2027.json --pdf outputs/official-audit/bodies/2d1ee89f2e084a1bf3a6b824b5333ff8b28daa9110e40ff6a534d02fe3f48e37.pdf --database "$env:USERPROFILE/SOGHRuntime/Admissions/admission_media_v0_4.sqlite" --output outputs/new-law-run --collab ../SOGH-collab
python -X utf8 -m admissions_pipeline.generic --profile config/profiles/niigata-humanities-recommendation-2027.json --pdf outputs/official-audit/bodies/2d1ee89f2e084a1bf3a6b824b5333ff8b28daa9110e40ff6a534d02fe3f48e37.pdf --database "$env:USERPROFILE/SOGHRuntime/Admissions/admission_media_v0_4.sqlite" --output outputs/new-humanities-run --collab ../SOGH-collab
python -X utf8 -m pytest tests/test_national.py -q -p no:cacheprovider
```

出力ディレクトリは実行ごとに新しい名前を指定する。`--collab` はClaude QAリポジトリの実際のパスに置き換える。同じDBに同じ入力を再投入しても事実・記事は増殖しない。QA結果は実行別に保存する。

## 版と移行

v0.2原本は変更なし。v0.3の移行前バックアップから別名のv0.4 DBを作成した。移行前には毎回SQLite backupを作成し、そのハッシュを記録する。旧11テーブルの既存行がすべて残ること、外部キー、integrity_checkを独立照合した。

`cycle_dimensions` は既存サイクルの分類を補足する。`admission_offerings` は同一サイクルに複数募集期・複数学科スコープ・複数入学月を保持できる。異なる年度は既存 `admission_cycles` で分ける。入学月が未確認なら空配列＋unconfirmedとして設定し、DBではNULLを保持する。新潟の入学月は資料内の明示を確認できず未確定。4月と推定しない。

新版PDFは別ハッシュで旧事実を残す。同じPDFの抽出誤りを修正する場合は、既存のimmutable制約により自動上書きできない。明示的な訂正移行が今後必要。最新行を無条件採用する仕組みや自動公開は実装していない。

ロールバック：書き込みを止め、移行前バックアップを別名DBとして復元・QAした上で参照先を戻す。稼働中DBへコピーを上書きしない。

## 新しい大学を加える手順

1. 公式ホスト・募集要項入口・お知らせ・FAQ・訂正ページを設定する。取得条件とrobotsを確認する。
2. 公式資料を取得し、年度・対象方式・表・注記を原本と画像で確認する。
3. `config/profiles/` に版ハッシュ、対象スコープ、アンカー、値変換、原典に沿う文章、未確認事項を登録する。表の行や列をまたぐ場合は複数の根拠アンカーを必須とする。
4. 新しいfact_keyが必要ならClaude #19で先に合意する。現在は既存キーのみを使用する。
5. 別名DBで実行し、CLI QAに加えて `scripts/verify_national.py` で原典引用・数値・既存行保全を確認する。
6. 原本PDF・ページ全文・snapshot・全文入りDBを除き、必要最小限の引用と検査報告をIssue/PRへ渡す。

これは任意レイアウトを自動理解する抽出器ではない。新資料のアンカー設定と表のレビューは必要。旧2方式は既存の専用抽出器を維持し、新方式から設定型に移行する。

## 運用上の境界

収集は手動CLIとして動作確認済み。旧夜間ワーカーは終了済みで、再登録・再起動していない。全国の自動巡回や定期通知の常時稼働とは区別する。収集CLIは同一出力ルートにつき1プロセスで運用する。

APIキーの値は読み出し・記録せず、環境変数の存在のみを確認。Gemini/Google API環境変数は未設定だった。外部AI APIは呼ばず、課金は発生させていない。
