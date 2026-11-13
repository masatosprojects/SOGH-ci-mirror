# Work 第2段階の検証済み成果物

Issue #26 / #17 / #28。実装・起動/停止・実資料でのQA付き更新を実行。監視サービスは停止済み。本番スケジューラ登録/変更/起動0、AI API呼び出し0、note投稿0。

詳しい運用・復元・未完了事項は UPDATES_V0_5.md、原典と適用範囲は OFFICIAL_UPDATES_V2.md。

- samples/current/active-state.json：既存根拠IDを保持する全体ビュー50根拠13草案。確定契約1.5.1で全13記事の正例QA/原典照合は合格。ただしqa/full-view-final.jsonの生の回帰能力検査は反転78/83で不合格・意味未検証22項目。閾値を下げず記録している（#39）。旧納品とIDが重なるため既存CIの新規export探索対象ではない。全件再検証CLIはpipeline/scripts/verify_full_view.py、CI接続依頼は#36。
- samples/general/claude-compatible-export.json：筑波KLIS一般選抜前期の独立6根拠3草案。既存CIの自動回帰対象。学類・専門学群選抜の範囲に限る。
- pipeline：Workの収集・改訂・移行コードとテスト。既存GitHub CIはこのサブディレクトリのテストを走らせない。実施結果は qa/work-tests.json。
- qa：ローカル原典照合、旧DB行保全、再実行、Windows起動停止、失敗・復元の記録。HTMLの完全な独立意味検査や将来の改訂承認を保証しない。
- database-schema.sql：構造のみ。原本PDF、全文、SourceSnapshot、実SQLite、秘密情報、QA実装のコピーは含めない。

元のv0.2/v0.4は無変更。v0.5作業DBとバックアップはローカル専用。GitHubだけから旧原本DBを復元できるとは扱わない。一般選抜の個別資格・全教科配点・将来の欠員補充人数等は未確認。
