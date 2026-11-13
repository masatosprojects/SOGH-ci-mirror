# Work の 5 PR の現在の head の独立再レビュー（2026-11-03、第 2 版）

**対象（現在の head、すべて open・Claude は統合していない）：#94 `93b3b34`、#96 `9c31f6d`、#99 `232fdf8`、#103 `0b3b034`、#109 `d0345a6`（Draft）。** 各 head は、前回の再レビュー（`WORK_FIVE_PR_REREVIEW_2026-11-03.md`、当時の head）から **1 コミットずつ**（「master `fe36208` 上で候補を進める。正式な有効化なし」）。以前の `PASS_WITH_WARNINGS` は現在の head の合格を意味しない。判定は**候補としての再レビュー**で、契約の受理・ゲートの合格・運用への適用の承認ではない。M1 は 2/8（g4・g8）、NOT ACCEPTED。Work のファイルは編集していない。
**環境**：Windows・Python 3.12、master `3109287`＋5 つの head を合わせたまっさらなチェックアウト（ローカル。**GitHub Actions は起動せず CI の結果はない**。Linux・Python 3.11 は未実行）。保存原典・監査コピーは読み取りのみ。

## 0. 試験
| | 件数 |
|---|---|
| Work の試験（無変更、各ディレクトリ） | #94 39、#96 41、#99 20、#103 46、#109 81 ＝ **227 成功**（失敗 0、skip 0） |
| `pytest tests/`（master＋5 つの head、Claude の独立試験を含む） | **2307 成功**・失敗 0・skip 0。回帰レポート（skip を失敗扱い）・全体ビュー・Work の CLI も成功 |
| 前回から変わった Claude の旧試験 | 旧 P-3 の期待値は master で回帰試験に反転済みなので、最新 head との組み合わせで**不一致 0** |

## 1. PR #94（`93b3b34`）— HTML の差分分類：`PASS_WITH_WARNINGS`（g2 未達）
- Work の新しい成果は「保存済みの HTML 2 件のバイト差の分類」（`html_revision_diff.py`、試験 12）。新しい取得はしていない。
- **私の独立の観察と一致**：FAQ は本文の外の WordPress のキャッシュ生成コメント（所要時間とタイムスタンプ）の 2 か所、Keio は script 内の要求 UUID の 1 か所だけが違う。私の側で、違うバイトは FAQ が 11 バイト（84 バイトの範囲）、Keio が 28 バイト（36 バイト＝UUID の長さの範囲）で、可視テキスト・リンク・年度・令和の文字列は完全に同一。
- Work の整理は妥当：「この差は保存バイトの違いを説明するだけで、真正性・適用年度・意味を示さない」「旧 HTML の真正性は `not_run`」「新しい HTML は新しい証拠で、旧 SHA の訂正ではない」。受理済みの訂正版の契約（`docs/EVIDENCE_CORRECTION_VERSION_CONTRACT.md`）と整合。
- 前回までの確認（receipt の独立検証、PDF の同一バイト、訂正候補 3 件・ID の再計算、旧行・facts・head の不変）は有効。**警告**：旧 HTML の真正性は未確認、新 ID の採番規則は未合意、意味確認は未実施。
- **残る 1 つ（g2）**：3 原典の live 取得による `official_site_authenticity=pass` を**登録する版**で成立させること。

## 2. PR #96（`9c31f6d`）— 0010 の SQL 案：`PASS_WITH_WARNINGS`（F-2 は未復元・未受容）
- 新しい成果：`0010-work-f2-archive-candidate.sql`（5 文・行なし）と、生成・検証の補助（`sql_candidate.py`、試験 12）。リポジトリの `src/db_contract/migrations` には**入れていない**。
- **私の G-2 契約（`docs/F2_G2_MIGRATION_AND_DB17_CONTRACT.md`）に対する独立試験 20 件**（`tests/test_pr96_sql_candidate_review.py`、Work の SQL を**文字列として読み**、私の登録の仕組みで適用。Work の harness は呼ばない）：
  - 構造：5 文のすべてが `CREATE`、`work_f2_` の表 1 つとトリガー 4 つ（更新・削除・置換・INSERT の能力ゲート）、行なし、他の物に触れない。作られる物は `work_f2_` の名前空間だけ。
  - 適用：履歴・チェックサム・`user_version=10`・DB-17 pass。凍結 0002〜0009 は不変（登録は 9 件のまま）。
  - **改変の検出（所有に登録した場合）**：ガード・INSERT ガード・置換ガードの削除、弱いガードへの差し替え、表の差し替え、余分な索引、`user_version` の巻き戻しが**すべて DB-17 の失敗**。登録なしでは DB-17 はこれらの物を見ない（G-2 の現状）。
  - INSERT：素の接続は拒否。能力は**9 引数**で、4 引数の別の関数は通らない。能力があっても UPDATE・DELETE・`INSERT OR REPLACE`・重複の INSERT は拒否。`restoration_state` は `archive_candidate_not_active` 以外を拒否。
  - アーカイブは正規の行・head・承認を動かさない。既存の無防備な `work_f2_*` を持つ DB は移行前に「ドリフト」として拒否（ファイルはバイト同一）。途中失敗はバイト同一。2 回目は何もしない。
  - SQL の文面は、Work の `recover_history.py` の定数から生成した内容と**正規化後に一致**（手で書き換えられていない）。
- Work が付けた**必須の対照**（実験用の登録簿あり＝DB-17 pass、なし＝未知の 0010 で fail）も、私の試験と同じ結論。
- **警告・条件**：`work_f2_` を所有プレフィックスに加える変更と、`MIGRATIONS` への正式な登録は Claude の変更で、**合意後**。DB-19（アーカイブの検査）は候補で、登録された QA の不変条件ではない。facts 5・cycle_editions 1 はアーカイブのみ、30 行の復元は別の判断。F-2 の受容の署名はユーザー。
- **残る 1 つ（g3）**：F-2 の受容の署名（ユーザー）。

## 3. PR #99（`232fdf8`）— 反復 299→308 の原因：`PASS_WITH_WARNINGS`（g6 未達）
- 新しい成果：`repeat_context_evidence.py` と `REPEAT_WINDOW_CAUSES.md`。実際の保存入力の分析で、**空の登録簿・ゲートは不変・承認の発明なし**。
- **私の独立の分類と一致**：新しい 9 件はすべて「5 記事の線を越えた形式の反復」（出典項目の窓 3、引用 ID・句読点の窓 3、行またぎ 2、実際の共有表現「大学入学共通テストの成績」1）。私の分類（出典項目 3・根拠を引く文 4・行またぎ 2）と同じ内訳。消えた反復は 0。
- Work の登録の**提案**（見出し 5・注意書き 1、`approved_by=null`）は使える登録簿ではなく、`load_rules` に渡さない扱いも正しい。日付の行をワイルドカードにしない点も妥当。
- **警告**：全体 QA は不合格のまま。実際の公式更新の E2E は `NOT_RUN`（保存 HTML の差はキャッシュ情報と要求 UUID だけで、新しい意味の更新は無い）。近重複の余裕（0.742／しきい値 0.8）は小さい。前提の view のハッシュ固定は継続の依頼。
- **残る 1 つ（g6）**：実際の公式更新を実際の経路で通し、合意したルールで全体 QA が通ること。

## 4. PR #103（`0b3b034`）— 題名と表の結合案、K-5：`PASS_WITH_WARNINGS`（g7 未達）
- 新しい成果：題名と表の**明示的な結合の証明書**（外部で固定した結合 SHA）、候補のジオメトリ、試験 9。80pt の検査器は**変更していない**（案の時点では）。
- 私の title scope 契約 v1.1（master に統合済み）と**補完的**：結合 SHA は、`reviewed_profiles` が固定する（profile SHA→原典 SHA・読み順）対応の根拠として使える。**採用する**：Work の結合 SHA を、title scope・`expected_table_clusters` と合わせてレビュー済み profile の固定に入れる。
- **K-5 に関する訂正（Claude 側）**：Issue #122 への私の最初の回答「矩形の下端を 724.8 に締めれば警告は消える」は不完全だった。Work の指摘どおり、**下端の吸着は実在の語の枠を切る**。独立に確認：最後のラベルの最後の字の枠は下端 **728.6**、インクは **約 720.3**（罫線の内側）。→ 検査器を v1.2 にして、インクがセルの内側なら枠のはみ出しを `info` に分類（実 PDF の 4 件が `info`）。Work の候補（最後のラベルの上端 633→629.52）は有効な改善（警告 4→3）。
- fact_key `admission_category_quota`（Work の仮称）は、粒度（大学・学部・学科＋入試区分＋募集枠＋入学年・月＋原典版）と一次／二次の根拠の使い分けが私の案と一致。**正式登録は未合意**のまま。
- **警告**：1 区分のみ（5 区分を「対応済み 5 方式」に数えない）。隔離表 `work_g7_quarantine` は DB-17 の所有外。値ごとの出所の記録（特に実施年度）が必要。
- **残る 1 つ（g7）**：1 区分の DB 登録→記事→QA の E2E（承認済みの `fact_key` が前提）。

## 5. PR #109（`d0345a6`）— W3 v2 提案とローカル LLM 要件：`PASS_WITH_WARNINGS`（候補。正式 read 契約は未受理）
- 新しい成果：`W3_V2_CONTRACT_PROPOSAL.md`（**未受理・アダプターなし**）、`LOCAL_LLM_REQUIREMENTS_AND_EVALUATION.md`、評価テンプレート。
- 私の残りの指摘との対応（**紙の上で閉じた**。実装・受理は別）：
  - **W-3（出所の学部・方式・募集単位・年度）**：全スコープの組（`university_id`〜`stage`、`exam_year` を含む）が、スナップショット・出所・確認済み事実のすべてに必須。`null`＝未指定でワイルドカードではない。**解消案として妥当**。
  - 発行元・作成時刻・有効期限・版：`issuer`・`source_version`・タイムゾーンつきの `created_at`/`expires_at`・保持を持ち、ハッシュは完全性の参照であって発行元の証明ではない（署名の仕組みは別の判断）。**妥当**。
  - **W-4（unknown の説明に推測の数字）**：unknown は `{topic_id, scope, reason_code, value:null}` で、理由は**閉じたコード**。自由記述は、将来許す場合に既存ガードを通す。**妥当**。
  - 質問の分類（`general_practice`／`evidence_based_practice`／`experience_based_practice`）：私の指摘に合致。
  - **`fiscal_year` の写像は未解決のまま**（`entry_year` を既定にしない）。ユーザー判断 D-5 に残る。
- **P-3b**（Cf 以外の不可視文字）は**未解決**。Work の提案でも未対応。
- ローカル LLM 要件：設計のみ、全項目 `NOT_MEASURED`、モデルの取得なし（容量不足を理由に保留）— 私の評価契約（`docs/LOCAL_LLM_EVALUATION_CONTRACT.md`）と整合。
- **正式な read 契約は、独立の受理条件を満たすまで未受理。**

## 6. 全体回帰の確認
2307 件成功・失敗 0・skip 0。前回までの 2 失敗（旧 P-3 の期待値、納品物のマニフェスト監査）：旧 P-3 の期待値は反転済み。マニフェスト監査は、Work の実行が納品物の中に bytecode を書いた場合の失敗で、`PYTHONDONTWRITEBYTECODE=1`（`scripts/local_ci.py` は設定済み）なら起きないことを確認済み（`docs/MANIFEST_AUDIT_AND_BYTECODE_CONTRACT.md`）。

## 7. 実行していないこと（`NOT_RUN`）
GitHub Actions の CI、Linux、Python 3.11（今回の統合コピーでは）、私自身の公式サイトへの live 取得、人による意味・編集・使いやすさの確認、実際の公式更新の E2E、1 区分の正式な DB 登録、F-2 の復元・受容、OS の強制終了・電源断、運用 DB への適用。
