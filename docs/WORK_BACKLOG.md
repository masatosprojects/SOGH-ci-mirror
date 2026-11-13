# Work 実装バックログ（M1「汎用DB基盤の完成」に向けて）

Work は、この順で進める。**Claude は Work のファイル・DB・ブランチを変更しない**（監査・契約・テスト・CI のみ）。既存の Issue #12・#20・#21・#22・#26 と PR #42 を重複させず、それぞれの**残りの仕事**として整理した。
契約は `docs/DB_ACCEPTANCE_CONTRACT_V1.md`、ギャップは `docs/DB_SCHEMA_GAP_ANALYSIS.md`（G-xx）、移行は `docs/DB_MIGRATION_REQUIREMENTS.md`、全体の進捗は `docs/DB_COMPLETION_DASHBOARD.md`。
**提案（proposed）の項目は、Work が合意するまで正規スキーマではない**（Claude は決めない）。

**方針（ユーザーの決定 2026-11-01）**：(1) 編集確認・下書き保存許可・最終公開承認はユーザー本人。**note の非公開下書きは、最終公開承認より前に保存**する（下書き→ユーザーの表示確認→最終承認→公開）。`docs/PUBLICATION_POLICY.md`。**note への実アクセス・下書き保存・公開・本番DBの変更は許可されていない。**(2) 旧DB v0.2 は保全し、実DBの独立監査が完了するまで v0.5 系への全面移行をしない（`docs/DB_MIGRATION_POLICY.md`）。
**2段階に分ける**：**実DBの現状監査（読み取り専用の独立コピー）は早急に**（W-03）。**実DBの変更・移行は、監査と契約合意の後**（W-05・W-06・W-07）。現状確認のために変更を伴う操作をしない。コピーの作り方：`docs/DB_COPY_PROCEDURE.md`。

**依存関係**：W-03（コピー）が先頭。W-01（PR #42）→ W-02（`stage`）。W-04（ID空間、G-05）は W-03 と独立に Work の方針を決められるが、解消の確認は W-03 のコピーで。W-05（スキーマ v0.6 案）は W-03 の結果と Work・Claude の合意が前提。W-07（コピーでの再現）は W-03 の後、W-05 とは独立に実施できる。W-06（v0.2）は監査後の判断で、**移行はしない方針**。W-08（新様式）と W-09（一気通貫）は W-03・W-05 の後。

| # | 作業 | 対象・修正するコンポーネント | 確定した契約／提案 | 必要な入力 | 成果物 | Claude の検証 | 合格基準 | 依存 | 推奨PR |
|---|---|---|---|---|---|---|---|---|---|
| W-01 | **PR #42**（FAQ構造化・記事2本改訂）の統合 | 既存の `work/faq-structured-v3` | 登録簿 1.7.1、`docs/WORK_RESUME_HANDOFF.md` §9 | master（最新）、`docs/PROJECT_STATUS.md` の競合 | 競合解消、QA再実行、未検証 18→21 の更新 | 全体ビューの独立監査（`fullview`、`audit_handoff`） | CI 緑、Claude の更新した監査コメント、Ready 化は Work | なし | 既存PR |
| W-02 | **`stage` の実データ付与**（Issue #12） | 根拠 `EV-T27-04-49cb4d`（interview）と `EV-U-2895dfe26d3b`（fee_refund）に `stage: [1]` | 契約A（確定）：引用する文が使う序数 | 再生成 | 根拠の新版、記事の再生成 | 序数の入れ替えの変異（模擬で 10/12→12/12、全体ビュー 10/14→14/14） | **見逃し 2→0 を Claude が実測** | W-01 | W-01 に含めるか別PR |
| W-03 | **実DBのコピーと機械可読なスキーマの提供** | Work のローカル実DB（秘密・原本を含めない） | `db_audit --target-kind copied_real_db`（確定） | `sqlite3 <db> .schema`、DBの独立コピー | `research/inbox/work-db-copy/`（スキーマ出力のみ可。コピー自体の置き場は相談） | `db_audit` と旧コピーとの比較（DB-09）を実行し、`DB_CURRENT_STATE_AUDIT.md` の [R] 項目を埋める | fail 0、warn と not_run の一覧 | なし（最優先） | 提供のみ（コード変更なし） |
| W-04 | **根拠ID空間の重複の解消**（G-05）。調査結果：`docs/G05_EVIDENCE_ID_ANALYSIS.md` | ID生成（`extract.py:89`、プロファイルの `code`）、`samples/general`（`EV-G27C-*`）と全体ビュー（`EV-G27-*`）、`facts` の UNIQUE | 提案：内容による同一性、`evidence_aliases`（旧IDを上書きしない）、`UNIQUE(case,source,fact_key,locator_hash)`、IDを内容から作る、または `code` を再抽出で変えない | Work の方針（1事実1ID か） | 方針の記録、必要ならID表・別名表 | `fullview`（重複は警告、矛盾は失敗）と `tests/test_db_acceptance_compat.py`・`tests/test_evidence_identity.py` が変わる | 全納品を1つのDBに入れて DB-01・06 が pass、`UNIQUE` の粒度を合意 | W-01（独立に決められる）。解消の確認は W-03 のコピーで | 別PR（方針→実装） |
| W-05 | **スキーマ v0.6 案（追加のみ）** | `database-schema.sql` と移行 | 提案：G-02 `schema_migrations`／`user_version`、G-03 索引、G-04 NULL 学科の UNIQUE 索引、G-06 `published_at`・`source_kind`、G-07 `revised_article_evidence`、G-09 追記専用トリガー、G-11 改訂理由 | W-03（実DBの実態） | 移行スクリプトと新スキーマ、コピーでのドライラン | 前後の `db_audit --baseline`（DB-09 pass）、`tests/test_db_acceptance_*` の拡張 | 旧行不変、冪等、逆方向（復元）、fail 0 | W-03、合意 | 項目ごとに小さなPR |
| W-06 | **v0.2 → v0.5 の方針**（G-01） | v0.2 の `publications`・`review_status`・`article_plans` の行き先 | `docs/DB_MIGRATION_REQUIREMENTS.md` §3 | ユーザーの判断（v0.2 のデータは2サイクル・27事実のサンプル） | 移行する／しない（理由）の記録 | する場合は対応表と前後の監査 | 決定が記録される | W-03 | Issue 回答 |
| W-07 | **実DBのコピーで移行・中断・復旧・冪等を再現** | コピーに対する stage/finalize・バックアップ・ロールバック | 契約 DB-5 | W-03 | 再現の記録（コマンドと結果） | Claude が同じ手順で再計算 | 旧有効版が壊れない、DB-09 pass | W-03、W-05 | 記録のみ |
| W-08 | **異なる資料様式の大学・方式を設定で1つ追加**（Issue #20・#21） | 抽出プロファイル、DB | 契約 DB-7、WP10.1 | 原本PDF/HTML（許可された範囲） | 新サイクルの根拠・記事草案 | 同じ受け入れ基準（全 DB 検査＋記事QA＋変異）、原典照合（原本が提供されれば） | スキーマ変更なしで合格 | W-01、W-03 | 大学ごとの別PR |
| W-09 | **公式更新→DB改訂→記事改訂の一気通貫**（P4・P8、Issue #17・#26 の残り） | 取得→差分→候補→QA→有効化→影響記事の改訂 | 契約 DB-5・DB-6 | 本当に1件変わった（または模擬の）旧版・新版 | E2E の記録 | 影響する記事だけが改訂され、旧版・head が保全されることを再計算 | 影響のない記事は不変 | W-05、W-07 | 別PR |
| W-10 | **公表日・種別・原本の確認**（G-06） | 資料の公表日（不明は null）、原本の保管場所 | 提案 | 公式ページ | 列の追加と値 | `published_at` を持つ事実の監査、原典のバイト列照合（原本があれば） | 公表日と取得日を区別して表示できる | W-05 | W-05 に含める |

## 承認フローの実装（W-11：Work の投稿処理。**合意が先、実装は後**）
Claude の契約（`docs/PUBLICATION_POLICY.md`、`src/db_contract/approvals.py`）が Work の実装に影響する点。**合意まで実装しない。note には接続しない。**
- 投稿処理は、**ユーザーの署名つきイベント**（`draft_save_authorized`、`publish_approved`）が無ければ下書き保存・公開をしない。イベントは版・本文ハッシュ・対象環境に結ばれる。
- 下書き保存・公開は冪等キーで一度きり。**開始して報告の無い試行は、盲目的に再試行しない**。保存した下書きIDを記録し、ユーザーの確認と最終承認は同じIDでなければならない。
- 承認後に本文・タイトル・根拠が変われば新しい版（承認は引き継がれない）。QA結果は本文ハッシュと有効期限に結ぶ。
- Work に必要な項目：状態表・承認表のスキーマ案（G-08、追加のみ）、冪等キーと下書きIDの保存、イベントの検証（鍵は Work が持たない）、モックでの先行試験。**ユーザーの証明の鍵の管理は未決**（ユーザーと決める）。
- 受け入れ：Claude の `tests/test_approval_contract.py` と同じ20の異常系が Work の実装に対して通ること（モックの note で）。

## W-03 の独立監査結果と Work への追加依頼（2026-11-01、`docs/DB_REAL_COPY_AUDIT.md`）
PR #59 は **PASS_WITH_WARNINGS**（実コピーの再計算は Work の報告と一致。原本・原典は未確認）。Work への依頼：
1. **F-1**：`privacy_report` の `user_path` パターンを区切りの連続（`[\\/]+`）に直し、v05・v06 の `update_batches.qa_json`（13／14セル）を含めて再生成。値は出さない。
2. **F-2**：v03→v04 で事実5件・記事6版・`article_evidence` 24行が上書き／消失した経緯の説明（開発途中の上書きか。受容してよいかはユーザーの判断）。以後は `--baseline` の組を v03→v04 も含めて示す。
3. **F-3**：G-04（空の学科1件）・G-05（同じ事実が2つの case_id）の方針（W-04）。実コピーに在るので g1 を止めている。
4. **F-4**（軽微）：コピー取得ツールは、検査が失敗したら書きかけのコピーを成功扱いにも放置にもしない（隔離または削除の記録）。空き容量の確認を追加。
5. 以後の実DBの更新ごとに、更新前後のコピー（`--baseline`）と `copy_identity` を提出。Claude が同じ手順で再計算する。

## 実施順序（Work 復帰後の最優先）
1. **W-01**（PR #42）→ 2. **W-02**（`stage`）→ 3. **W-03**（実DBのコピー）→ 4. **W-04**（ID空間）→ 5. **W-05**（スキーマ案、合意しながら小さく）→ 6. **W-07**（実DBのコピーで再現）→ 7. **W-08**（新様式）→ 8. **W-09**（一気通貫）。W-06 と W-10 は並行で判断・実施。
**M1 の完成は、W-03・W-07・W-08 が実データで確認され、`docs/DB_COMPLETION_DASHBOARD.md` の M1 ゲートがすべて ✅ になってから。**
