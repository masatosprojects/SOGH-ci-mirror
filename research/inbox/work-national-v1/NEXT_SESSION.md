# 次回 Work 再開

1. master、AGENTS、担当Issue #14/#17/#19/#20/#21/#22、新しいClaude PRを確認する。
2. `OFFICIAL_UPDATE_AUDIT.md` の追加案内を優先する。慶應の緊急メンテナンス、既に現行PDFに入っている多言語評価、筑波ACのAI利用FAQと返還案内を区別する。
3. #19で必要な根拠形式を合意し、新事実を原典から登録する。古い人数・日付を自動上書きしない。募集要項の追加告知については「変更なし」扱いにしない。
4. 新しい一般選抜/共通テスト方式をJSONプロファイルで少数追加する。表の行・列と注記を画像で照合し、不明値は保留する。
5. 原典PDFを含む実データE2E、独立QA、テストを行い、WorkブランチのPRで渡す。原本・全文・DB本文は送信しない。
6. 定期運用を接続する場合は、未完了の実処理を投入し、空キューの繰り返しを開発の進捗として報告しない。

ローカルのv0.4実行用DBはユーザープロファイル配下 `SOGHRuntime/Admissions/admission_media_v0_4.sqlite`。原本とsnapshotはSOGHの `outputs/official-audit-v2/`、最新新潟草案は `outputs/national/niigata-release/` と `outputs/national/niigata-humanities/`。バックアップは各実行ディレクトリ。
