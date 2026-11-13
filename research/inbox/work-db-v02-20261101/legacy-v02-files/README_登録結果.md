# 全国大学入試情報メディア：公式資料登録・記事試作 v0.2

## 今回実装したこと
- SQLite v0.1 の既存17テーブルを維持して、2027年度入学向け2選抜のデータを投入。
- 2大学、2入試サイクル、公式資料2件、個別の公式事実27件（事実とPDFの節・ページを関連付け）。
- 記事シリーズ3種 × 2入試 = 6つの記事草案（`article_drafts/`）および生成AIへの入力JSON（`article_inputs/`）を生成。
- 既存SQLiteの整合性・外部キー制約・出典不足チェックを実施。

## 要注意：PDF原本の保存について
この実行環境では公式サイトPDFのファイル本体をダウンロードできなかったため、`source_extracts/` は**公式PDFの該当ページをブラウザから読んで作成した短い確認用の要約**です。**公式PDFそのものではありません**。

`source_snapshots.content_sha256` はローカルの要約抜粋ファイルのSHA256値であり、**公式PDFのSHA256を示すものではありません**。`source_snapshots.media_type` も `text/plain` です。原本PDFを後日取得できたら、別のsnapshot行として追加してください。自動的に原本保存済みとは扱わないでください。

## 出典原本URL
- 筑波大学 令和9年度AC入試学生募集要項（2026年6月公開）：https://ac.tsukuba.ac.jp/wp/wp-content/uploads/2026/06/AC_youkou2027_sec.pdf
- 慶應義塾大学 2026夏秋AO募集要項（2026年5月公開）：https://www.keio.ac.jp/files/91dad17f3e88ef4a0706cfa0fd02c03eefe8010dac2cda39c8e8c1bb02f46ac6

## 生成した記事
- 入試の基本情報：各校1件
- 出願の準備：各校1件
- 面接の形式と対策：各校1件

原稿は**AIによる深掘りや推敲前の機械的な記事試作**です。ChatGPT/Gemini APIを呼び出したものではありません。検索エンジン最適化・文章の自然さ・記事の独自性は未評価で、人による事実確認を終えるまで公開しないでください。

## 意図的に登録していないこと
- 面接官の人数や実際の質問（公式資料では確認できないため）
- 特定の個人の受験体験・合否（同意と匿名化が未整備のため）
- 入試倍率や合格確率（年度と公式数値の未照合のため）
- 慶應SFCの150名を夏秋AO単独の定員として扱うこと
- PDF全文の複製・再配布

## 運用とアップロードの扱い
- `admission_media_v0_2.sqlite`はローカルで作成した実行可能DB。
- Googleドライブへのアップロード、noteへの下書き保存・公開は**今回の処理ではしていません**。
- 最終的には原本PDFをドライブに保存し、DriveファイルIDを`source_snapshots`へ追加。元PDFと要約抜粋のハッシュは別管理します。
- 旧ボットの`poster_note_playwright.py`へ接続する前に、投稿アダプタとセキュリティ検証が必要です。

## 検証する
```
python - <<'PY'
import sqlite3
c=sqlite3.connect('admission_media_v0_2.sqlite')
c.execute('PRAGMA foreign_keys=ON')
for t in ('universities','admission_cycles','fact_claims','article_versions','publications'):
 print(t,c.execute('SELECT count(*) FROM '+t).fetchone()[0])
print('integrity:',c.execute('PRAGMA integrity_check').fetchone()[0])
print('missing_evidence:',c.execute('SELECT sum(missing_evidence_count) FROM v_article_fact_health').fetchone()[0])
```

## 次の実装
1. 公式PDFの原本バイト列の正規取得と個別ファクトの該当ページ一致テスト。
2. 重要主張の複数出典・修正告知チェック、自動差分監視とstale化。
3. 情報パックからGeminiプロンプト組立、生成テキストのfact_id機械検証。
4. noteへの下書き専用投稿テスト（利用規約・アカウント認証確認後）。
