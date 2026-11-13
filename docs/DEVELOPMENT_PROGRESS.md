# 開発進捗（受け入れ条件で数える）

数値の要約（最終報告と同じ文字列）：`工程 P0:1/4 P1:3/4 P2:5/10 P3:2/5 P4:4/5 P5:6/7 P6:0/5 P7:3/8 P8:0/5 P9:0/5 P10:0/4｜DB DB-1:4/7 DB-2:3/7 DB-3:5/7 DB-4:3/7 DB-5:4/7 DB-6:3/7 DB-7:3/7｜M1 8/8`

> `docs/development_progress.json` から自動生成。**テスト件数・PR数は進捗ではない。** 進捗＝証拠つきで検証済みの受け入れ条件 ÷ 受け入れ条件の総数。未確認・未実施・合成データだけの確認は加算しない。

| 工程 | 内容 | 主管 | 検証済み／条件 | 進捗 | WPの状態 |
|---|---|---|---|---|---|
| P0 | 事業要件・情報表示・権限・公開ルール | User＋両者 | 1／4 | 25% | design 2、not_started 2 |
| P1 | 既存システム・DB・原典の棚卸し | Work＋Claude監査 | 3／4 | 75% | accepted 1、design 1、implementing 1、not_started 1 |
| P2 | 汎用DB設計・移行・履歴・安全性 | Work実装／Claude契約・QA | 5／10 | 50% | QA_pending 6、design 1 |
| P3 | 公式資料の収集・抽出・構造化 | Work | 2／5 | 40% | QA_pending 4、implementing 1 |
| P4 | 更新監視・版差分・影響分析 | Work＋Claude | 4／5 | 80% | QA_pending 3、implementing 1 |
| P5 | 独立QA・回帰・監査 | Claude | 6／7 | 86% | QA_pending 4、implementing 1 |
| P6 | 記事企画・生成・文章品質 | Work＋Claude | 0／5 | 0% | implementing 2、not_started 3 |
| P7 | 承認・note下書き・公開ゲート | Work＋Claude＋User | 3／8 | 38% | design 1、not_started 4 |
| P8 | 一気通貫E2E・障害復旧 | 両者 | 0／5 | 0% | design 2、not_started 3 |
| P9 | 限定運用・公開前品質評価 | User承認＋両者 | 0／5 | 0% | not_started 5 |
| P10 | 全国展開・新年度・継続改善 | 両者 | 0／4 | 0% | not_started 5 |

## 受け入れ条件（工程ごと）

### P0 事業要件・情報表示・権限・公開ルール

- ✖ 利用対象（読者）と記事タイプ、対象外（合否の断定・個人別の資格判定）が決まっている
- ✖ 情報表示規約（入学年度と実施年度、取得日と公表日、確定と未確認、失効情報、訂正の見せ方）が文書になっている
- ✅ 公開決裁・編集確認・下書き保存許可の権限（いずれもユーザー本人。AI・CIの成功は承認でない）と、下書き→確認→最終承認の順序が文書で決まっている（決定のみ。実装は P7）　— 証拠：docs/PUBLICATION_POLICY.md（ユーザーの決定 2026-11-01）
- ✖ リスク・予算（API費用上限、著作権、note規約、人の確認範囲）が決まっている

### P1 既存システム・DB・原典の棚卸し

- ✅ リポジトリにあるDBの構造（3世代）を、コード・スキーマ・サンプルから確認し、根拠の種類を区別して記録した　— 証拠：docs/DB_CURRENT_STATE_AUDIT.md、reports/db-audit/、tests/test_db_acceptance_compat.py
- ✅ Work のローカル実DBのスキーマ・テーブル・行数・有効版を、コピーで確認した　— 証拠：copied_real_db：5世代のコピーのスキーマ・表・行数・有効版（根拠50・記事13）を Claude が独立に再計算（reports/db-audit/real_copy_independent_audit_2026-11-01.json）
- ✅ 現行の50根拠・13草案が、納品スキーマに入れて整合する（サイクル・原典・記事・改訂への追跡）　— 証拠：tests/test_db_acceptance_compat.py（repository_sample、派生）、reports/db-audit/audit_current_view_loaded.json
- ✖ 実行コマンド・as_of・入力hash・成果物hash・依存版が固定され、第三者が保存した入力から再現できる

### P2 汎用DB設計・移行・履歴・安全性

- ✅ 受け入れ契約（DB-1〜DB-7）が、フィールド・型・一意性・不変条件・失敗時の動作で文書化された　— 証拠：docs/DB_ACCEPTANCE_CONTRACT_V1.md
- ✅ 読み取り専用の独立監査 CLI がある　— 証拠：src/integration/db_audit.py、tests/test_db_audit.py
- ✅ 正常系の受け入れ試験が合成DBで合格　— 証拠：tests/test_db_acceptance_normal.py（synthetic）
- ✅ 異常系（不正データ・履歴の破壊・障害注入・後方互換）の試験が合成DB/リポジトリのサンプルで合格　— 証拠：tests/test_db_acceptance_{invalid,history,faults,compat}.py（synthetic / repository_sample）
- ✖ 実DBのコピーで db_audit が fail 0
- ✖ 実DBのコピーで移行・中断・復旧・冪等性を再現した
- ✖ 異なる大学・資料様式・年度を設定追加で足し、同じ受け入れ基準を満たした
- ✖ 契約のギャップ（G-01〜G-13）が Work と合意され、解消またはリスク受容された
- ✖ 契約の提案項目を Work と合意して確定した
- ✅ 旧DB v0.2 の保全と、v0.5 系への全面移行の保留の方針が決まり、保全対象と再検討の条件が文書になっている　— 証拠：docs/DB_MIGRATION_POLICY.md（ユーザーの決定 2026-11-01）

### P3 公式資料の収集・抽出・構造化

- ✅ 納品済みの根拠の一部（筑波AC・慶應のPDF）が、原本と一致することを独立に確認した　— 証拠：audit_handoff --pdf-dir（source_pdfs・values_in_quotes が pass）。PR #41 の監査記録
- ✅ 公式FAQの引用文が、現在の公式本文に存在することを独立に確認した（本文の一致。バイト列の一致ではない）　— 証拠：PR #42 の先行監査コメント（6引用文）、PR #42 最終監査（b23a9f9／d638d85、reports/pr-audit/pr42_final_audit_2026-11-01.json）：保存 HTML の SHA 再計算、6 引用の保存位置の再現、公式の現行ページの生バイト列 SHA が保存版と一致
- ✖ 納品済みのすべての根拠について原本照合を実施した
- ✖ 誤ページ・誤年度・曖昧数値・欠落で有効化しない（fail closed）ことを、独立の負例で確認した
- ✖ 新しい資料様式の1方式を設定だけで追加し、原本→根拠→DB→記事→QAが通った

### P4 更新監視・版差分・影響分析

- ✅ 版の差分（ページ・行・値）と、根拠・記事への影響分類が実装され、負例も試験された　— 証拠：src/versioning/、docs/VERSIONING.md、tests/test_versioning*.py
- ✅ 監視の失敗・再試行・二重起動・停止が、模擬通信で試験された　— 証拠：tests/test_audit_work_v2.py（synthetic）
- ✖ 実際の更新（本当の差分）から DB 改訂・記事改訂までを一気通貫で再現した
- ✅ 承認付きの差分反映が冪等で、旧版を保全する（合成DB）　— 証拠：tests/test_db_acceptance_{normal,faults}.py（synthetic）
- ✅ 模擬の更新で、影響する記事だけが改訂され、過去版・head が保全された（実データ）　— 証拠：copied_real_db（Work の v05→v06 コピー）：FAQ の根拠 1 件を改訂すると、それを引用していた筑波AC の 2 記事だけが改訂され、他の 11 記事は本文が同一、旧行・旧版は全て保全（旧IDの引用は旧 head に残る）。Claude が DB だけから再計算（reports/pr-audit/pr42_final_audit_2026-11-01.json、PR #42 の監査コメント）。範囲：コピー上の構造化改訂 1 件。原典の差分に起因する更新ではない（P4.c3 は未達）

### P5 独立QA・回帰・監査

- ✅ 構造QA（スキーマ・fact_key・年度/方式・原本hash・引用ID・値・日付・数量・stage）が実装され、全納品に適用されている　— 証拠：src/verify/、docs/STRICT_VALIDATION.md
- ✅ 文章QA（意味の反転・未支持の義務・禁止・免除・言い換え）が、封印した評価セットで汎化を測定されている　— 証拠：docs/STRICT_VALIDATION.md（封印セット F 94.0%、D/E は開発用）
- ✅ coverage が、検証済み／矛盾／未検証／対象外を分け、未検証を検出に数えない　— 証拠：src/verify/qualitative.py、docs/REGRESSION.md
- ✅ 回帰（変異・引用差し替え・反転・表記ゆれ・版管理・全体ビュー）が CI で毎回実行され、閾値が下げられていない　— 証拠：.github/workflows/tests.yml、src/regression/
- ✅ 監査が Work の報告に依存せず、納品物・manifest・DBコピー・原典を再現する（原典未提供は not_run）　— 証拠：src/integration/audit_handoff.py、PR #41/#42 の監査
- ✅ 自動検証の限界（未知の言い換え、構造化されていない義務、原典）が明示されている　— 証拠：docs/STRICT_VALIDATION.md、docs/WORK_RESUME_HANDOFF.md
- ✖ 既知の見逃しの類型（評価者の述語、許可の弱い語、構造化されていない義務）が解消された

### P6 記事企画・生成・文章品質

- ✖ 記事タイプごとの目的・読者ニーズ・重複範囲が決まっている
- ✖ 記事が事実・助言・未確認・出典・作業基準日・変更履歴を分離している
- ✖ 同じ入力から同じ記事版が得られることを独立に確認した（決定的なテンプレート）
- ✖ AIライターの採否が、評価基準に基づいて決まった
- ✖ 記事ごとの評価（正確性・読みやすさ・有用性・重複・網羅・期限）が実施された

### P7 承認・note下書き・公開ゲート

- ✅ 自動化（CI・QA・DB）が記事を公開可にできない（publish_allowed=0、publication_approved=false）　— 証拠：docs/REGRESSION.md、DB-06、src/regression/fullview.py
- ✖ 記事版の状態遷移（generated→QA→review→approved→draft_saved→published→corrected/retired）が実装され、実行者・理由・時刻を残す
- ✖ 公開ゲート（原本照合・年度・期限・未検証・人の最終確認）が実装された
- ✖ noteアダプタが隔離環境で検証された（モック→許可後に非公開下書き）
- ✖ 記事版↔noteの下書き/公開URLの対応、1版1下書き、失敗・再試行・再読込照合が試験された
- ✖ 非公開下書きの保存→読戻しが、明示許可の範囲で再現された
- ✅ 9つの状態と、誰がどの状態に進められるかが、実行できる仕様と試験になっている（仕様のみ。DBにも運用にも実装されていない）　— 証拠：src/db_contract/publication.py、tests/test_publication_policy.py
- ✅ 承認イベント（版・本文ハッシュ・署名・QA有効期限・冪等キー・欠落の拒否）の契約が、20の異常系を含めて、ローカルのモックと合成データで試験された（note には接続していない）　— 証拠：src/db_contract/approvals.py、tests/test_approval_contract.py

### P8 一気通貫E2E・障害復旧

- ✖ 公式更新→取得→抽出→DB候補→QA→有効化→影響記事の改訂→QA→承認→下書きが、隔離環境で一気通貫に再現された
- ✖ 障害注入（サイト停止・クラッシュ・DB書込失敗・CI失敗・ブラウザ保存失敗・認証切れ・同時実行・重複トリガー）が隔離環境で再現された
- ✖ 復旧（前回有効版の保護・再開位置・冪等・手順書・バックアップ復元）が実証された
- ✖ 失敗・長期未更新・期限切れ・原典消滅・差分の通知と、費用・レート上限が実装された
- ✖ 運用権限（本番タスク・トークン・secret・承認者不在での停止・監査ログ・手動停止）が決まり実装された

### P9 限定運用・公開前品質評価

- ✖ 対象（少数の方式。資料様式が異なるものを含む）が選定された
- ✖ 公開前レビュー（最新版・注記・数値・期限・未検証・リンク・可読性・誤認）の手順が人で実施された
- ✖ 安全な下書き運用が観察された（公開はユーザーの承認後のみ）
- ✖ 実際の更新による DB・記事の更新と訂正表示が追跡された
- ✖ 成果指標（根拠網羅率・原典照合率・重大誤記・遅延・保守負荷・工数）が測られ、無承認公開・重複投稿が0

### P10 全国展開・新年度・継続改善

- ✖ 新大学導入パック（大学情報・方式・資料URL/版・抽出プロファイル・fact_key契約・初回レビュー・サンプル記事・QA）が定義され、実際に1大学で使われた
- ✖ 新年度の更新で、旧年度と新年度が分かれ、昨年度記事が現役扱いにならない
- ✖ 新大学を足しても、既存のQAと履歴が壊れない（回帰）
- ✖ 品質・費用・人手負荷の定義済みの範囲が、運用の実測で維持されている

## ブロッカーと次の作業（WP単位、未完了のもの）

| WP | 状態 | 未検証 | 次の作業 |
|---|---|---|---|
| P0-WP0.1 利用対象と記事タイプ | `not_started` | ユーザーの決定が未記録 | ユーザーの判断 |
| P0-WP0.2 情報表示規約 | `design` | 規約の合意 | WP0.1の後に草案 |
| P0-WP0.3 公開決裁 | `design` | 実装（G-08）、ユーザーの証明の鍵の管理（未決）、Work の投稿処理、note の下書き保存・公開（未許可・未接続） | G-08 の状態表・承認表と、鍵の管理を Work・ユーザーと合意（P7-WP7.1） |
| P0-WP0.4 リスクと予算 | `not_started` | 予算・規約の確認 | ユーザーの判断 |
| P1-WP1.1 システム地図 | `not_started` | SOGH本体・旧noteボット側は未確認 | Work 復帰後 |
| P1-WP1.3 3大学5方式の追跡表 | `implementing` | 実DBの追跡、原本ページ（引用から再構成） | G-05 を Work が解決 |
| P1-WP1.4 再現性 | `design` | 依存版・コマンドの固定 | 文書化 |
| P2-WP2.1 識別子 | `QA_pending` | 実DB、G-04/G-05 | Work：G-05 の方針（1事実1ID、別名表、UNIQUE の粒度）、G-04 の索引 |
| P2-WP2.2 原典トレース | `QA_pending` | 実DB、公表日、原典との照合（not_run） | Work：G-06 の合意 |
| P2-WP2.3 事実スキーマ | `QA_pending` | 実DB | 実DBのコピーで実行 |
| P2-WP2.4 stage契約A | `QA_pending` | 運用DBでの有効化（Work の判断とユーザーの承認が要る）、fee_refund の原典 SHA が source_documents に未登録、Issue #12 は未完 | Work：候補の有効化の判断、原典 SHA の登録（G-06・g2）。Claude：有効化後に実コピーで再確認 |
| P2-WP2.5 不変履歴 | `QA_pending` | 実DB、トリガー | Work：G-07/G-09/G-11 |
| P2-WP2.6 トランザクション | `QA_pending` | 実DBでの再現 | Work：実DBのコピーを提供 |
| P2-WP2.7 将来の負荷と移行 | `design` | 実DBの移行、性能、v0.2→v0.5 | 実DBのコピーの監査（W-03）。移行の検討は DB_MIGRATION_POLICY の10条件が揃ってから |
| P3-WP3.1 ソース登録 | `QA_pending` | 27資料の設定の独立監査 | Work 復帰後 |
| P3-WP3.2 取得 | `QA_pending` | gzip・壊れたPDF・URL移転の独立試験 | 追加の負例 |
| P3-WP3.3 原典保存と差分 | `QA_pending` | ローカル原本の保全 | Work |
| P3-WP3.4 抽出器 | `implementing` | 再生成・負例・新様式の独立確認 | Work |
| P3-WP3.5 出典付き正規化 | `QA_pending` | 人手レビューの列挙 | Work |
| P4-WP4.1 監視器 | `QA_pending` | 実運用（本番監視は禁止事項） | ユーザーの許可後 |
| P4-WP4.2 版差分 | `QA_pending` | 実際の原典の差分 | Work：実際の旧版・新版 |
| P4-WP4.3 影響グラフ | `implementing` | 投稿先との関係（G-08） | P7 の後 |
| P4-WP4.4 承認付き差分反映 | `QA_pending` | 実DB、原本根拠照合 | Work |
| P5-WP5.1 構造QA | `QA_pending` | 新しい大学・様式での検出率 | 新大学の納品ごとに回帰 |
| P5-WP5.2 文章QA | `implementing` | 未知の言い換えの完全な検出（限界を明示） | 評価者の述語・許可の弱い語（新しい封印セット G を先に作る） |
| P5-WP5.3 coverage | `QA_pending` | 構造化されていない義務は未検証のまま | 構造化の契約（Work と） |
| P5-WP5.4 回帰 | `QA_pending` | — | 新しい納品ごと |
| P5-WP5.5 監査 | `QA_pending` | 原典のバイト列、実DB | 実DBのコピー |
| P6-WP6.1 記事の目的 | `not_started` | — | WP0.1 の後 |
| P6-WP6.2 記事構造 | `implementing` | 助言と公式事実の分離の基準 | WP6.1 の後 |
| P6-WP6.3 コンテンツ組立 | `implementing` | 再現性の独立確認 | 再実行して hash を比較する試験を追加 |
| P6-WP6.4 AIライターの判断 | `not_started` | 未導入 | ユーザーの判断 |
| P6-WP6.5 記事ごとの評価 | `not_started` | — | WP6.1 の後 |
| P7-WP7.1 版ごとの公開状態 | `not_started` | 実装（Work と合意するまで既存DBに追加しない）、鍵の管理 | G-08 の合意 |
| P7-WP7.2 公開ゲート | `design` | Work の投稿処理への実装、人の承認の経路、鍵の管理 | P0 の決裁後 |
| P7-WP7.3 noteアダプタ | `not_started` | 入試DBとのnote連携は未実証（旧ボットのコードは別テーマ） | ユーザーの許可 |
| P7-WP7.4 重複防止と照合 | `not_started` | 実際の投稿処理での再現 | WP7.3 の後 |
| P7-WP7.5 配信表現 | `not_started` | — | P0 の後 |
| P8-WP8.1 ゴールデン経路 | `not_started` | 未着手（DB・下書きが前提） | P2・P7 の後 |
| P8-WP8.2 障害注入 | `design` | CI失敗・ブラウザ・認証切れ・E2E | P7 の後 |
| P8-WP8.3 復旧 | `design` | 実DB、手順書 | P2 の後 |
| P8-WP8.4 監視・通知 | `not_started` | — | 未着手 |
| P8-WP8.5 運用権限 | `not_started` | — | ユーザーの判断 |
| P9-WP9.1 対象選定 | `not_started` | — | P8 の後 |
| P9-WP9.2 公開前レビュー | `not_started` | — | 未着手 |
| P9-WP9.3 試行 | `not_started` | — | 未着手 |
| P9-WP9.4 実更新 | `not_started` | — | 未着手 |
| P9-WP9.5 成果指標 | `not_started` | — | 未着手 |
| P10-WP10.1 新大学導入パック | `not_started` | — | P2・P3 の後 |
| P10-WP10.2 新年度更新 | `not_started` | 新年度の実地 | 未着手 |
| P10-WP10.3 カバレッジ拡大 | `not_started` | — | 未着手 |
| P10-WP10.4 運用コスト | `not_started` | — | 未着手 |
| P10-WP10.5 企画改善 | `not_started` | — | 未着手 |
