# G-04・G-05 の契約（追加型。Claude の代行実装、2026-11-01）

## 0. ユーザーの決定（2026-11-05）
**G-04：A「未指定のまま受容」。G-05：A「別名を採用」。** ユーザーが、Claude の推奨（`docs/reviews/M1_UNMET_GATES_TASK_TABLE_2026-11-05.md`）に対して、チャットで「A で進める」と明示した（記録：Issue #55）。
- **G-04 A の意味：** 学科が空のサイクルは「学科は資料に明示なし」として受容する。推測で学科を埋めない。既存の NULL を更新しない・NOT NULL 化もしない。二重登録の防止は §1 の追加の一意索引で行う。
- **G-05 A の意味：** 5 群の同一事実は、旧 ID（`EV-G27C-*`）を改名・削除せず、`evidence_aliases` で根（`EV-G27-*`、位置訂正後の現行版へ解決）に別名として結ぶ。旧 ID・旧引用位置・旧記事の引用は不変。§2 の契約に従う。
- **この決定が承認しないこと：** 運用 DB への適用、正式な移行、F-2 の署名、30 行の復元、`fact_key` の正式登録、v0.2 の移行。これらは別の承認が要る。**ゲートの合格数は変えない（M1 は 2/8）。** 合格には、Work の契約の合意、運用 DB への適用の承認、適用後の実コピーでの再確認（DB-02/04/05/10/16〜18 と記事 QA）が要る。
- **今の状態：** 決定済み・未実施。実コピー（元の v06 の写し）の場所が未確認のため、決定を適用した使い捨てコピーでの再実行は保留。合成の試験（`tests/test_additive_schema.py`）は成功している。

**状態：`CONTRACT_ACCEPTABLE_WITH_CONDITIONS`（Claude の判断）。Work の合意が要る点は `WORK_CONTRACT_REVIEW_PENDING`。** 実装は `src/db_contract/additive_schema.py`（`SELF_VALIDATED`：Claude が書き、Claude が試験した。厳密な独立監査ではない）。**実DBの原本・監査コピーには適用していない。使い捨てコピーだけ。** 根拠：Issue #55 の Work の提案（2026-11-01 11:35）、`docs/G05_EVIDENCE_ID_ANALYSIS.md`、`docs/DB_SCHEMA_GAP_ANALYSIS.md`。M1 のゲートは変更しない。

## 1. G-04：学科が空のサイクルの重複防止
**Work の提案**：既存の NULL を更新・NOT NULL 化せず、`COALESCE(department,'')` を含む追加の UNIQUE 索引を、既存の case の粒度で張る。既存の衝突があれば適用を停止。**判断：条件つきで妥当。**

### 契約
| 論点 | 取り決め |
|---|---|
| 同一性の単位 | **サイクル（case）**＝大学・学部・学科・入試方式・入学年度（`fiscal_year`）。**`exam_year` は含めない**（既存の UNIQUE も含めていない。含めると同じ方式の別試験年が別になる） |
| NULL と空文字 | **同じ「学科未特定」**。推測で学科を補わない。既存の NULL を更新しない（NOT NULL 化もしない） |
| 募集期・募集枠・entry month | **サイクルを分けない**。同じサイクルの募集（`admission_offerings`）として別の行に持つ。この索引はサイクルだけを見る（慶應の 4 月・9 月の 2 募集は 1 サイクルの 2 offering のまま） |
| offering の同一性（**Claude の追加提案・`WORK_CONTRACT_REVIEW_PENDING`**） | `(case_id, round_name, COALESCE(entry_month,-1), scope_json, source_sha256)`。**月が未特定（NULL）の重複も止める**。-1 は実在の月になれない。別の資料（`source_sha256`）からの同じ募集は別の offering |
| 名前の揺れ | 文字列は**そのまま**比較（全角半角・空白の正規化はしない）。**限界**：「経済学部」と「経 済学部」は別になる。正規化した同一性は別の契約 |
| 同じ名称の異なる募集区分 | 方式名・scope が違えば別。DB は意味を推測しない |
| 既存行に衝突がある | **preflight が衝突を検出し、全体を原子的に停止**（何も変わらない。ファイルのバイト列も同じ）。ユーザー・Work が解消してから再実行 |
| 複数年度 | `fiscal_year` が違えば別のサイクル |
| 移行時の旧行の保全 | 旧行は一切更新・削除しない（索引の追加だけ） |
| UNIQUE 違反 | 追加時に `IntegrityError`。更新経路は既存の `stage` が事前に cross-cycle を拒否する |
| 将来のスキーマ変更での再適用 | 移行は `schema_migrations(migration_id, description, statements_sha256, applied_at)` に記録され、**再実行は何も変えない**。**表の作り直しは式の索引を落とす**ので、作り直す移行は索引を再作成し、`db_audit` で確認する（今後の検査の候補） |

### 正例・負例（`tests/test_additive_schema.py` と使い捨てコピーでの確認）
- 正例：学科・年度・方式・学部・大学が違えば別サイクル。月の違う offering は別。別の資料の同じ月は別。
- 負例：学科が NULL の二重登録が拒否される／空文字の二重登録が拒否される／offering の NULL 月の重複が拒否される／既存の衝突で全体が停止し、ファイルが不変／途中の失敗で何も適用されない／2 回目は何も変えない。
- 実コピー（v06 の使い捨てコピー）：慶應の学科なしサイクルに NULL・空文字の 2 件目が拒否される、慶應の 2 つの offering が保たれる、人為的な衝突で停止して不変。

### 影響
v06 の 5 サイクルに衝突は無い（preflight が通る）。既存の行は一切変わらず、`db_audit` は DB-01〜12 が pass のまま（DB-09 pass）。専用索引が 0 本から増える（G-03 の一部）。**適用は Work の合意と、運用DBへの適用の承認が要る。**

## 2. G-05：根拠 ID の root・別名・版
**Work の提案**：6 対応表（旧 `EV-G27C-0n` を改名・削除せず alias 候補として保全。01 の root は `EV-G27-01-e1137e`、位置訂正後の現行版は `EV-U-8d8e1d177883`）、論理 root と引用する版の分離、`UNIQUE(case,source,fact_key)` は単純に削除しない、新潟 2 学部の `postal_period` は独立。**判断：条件つきで妥当。**

### 区別する概念
| 概念 | 実体（現行DB） | 契約 |
|---|---|---|
| 論理 root | 最初に登録された事実（`facts.evidence_id`） | alias の行き先は **root** だけ。alias の alias は不可 |
| 現行版 | `evidence_heads` の head（`evidence_revisions`） | 版を固定しない alias は**現行の head**へ解決する（位置訂正後の版。誤った旧位置へ向かない） |
| 旧互換 ID・alias | 新表 `evidence_aliases` | 追記専用。旧 ID は改名・削除しない。**alias の名前は既存の根拠 ID と衝突できない**（以後に作られる根拠 ID も alias の名前を取れない） |
| 引用する版 | `article_evidence.evidence_id`（記事ごと） | 記事は版を固定して引用する。alias の登録は記事の引用を変えない |
| 固定した版 | `evidence_aliases.pinned_evidence_id`（任意） | その root の**改訂**でなければならない |
| 原典 SHA・locator・対象 case・年度・条件 | root の記録 | alias は同じ case・fact_key・原典・値でなければ登録できない（コード層）。DB は root の存在・case・fact_key を強制 |

### 契約（強制する場所）
| 規則 | DB | コード層（`register_alias`） |
|---|---|---|
| 存在しない root を拒否 | 外部キーと**トリガー**（接続が外部キーを ON にしていなくても） | ✓ |
| 別 case・別 fact_key の root を拒否 | 外部キーと**トリガー** | ✓（年度は case に含まれる） |
| 循環・alias の alias を拒否 | トリガー（root は alias にならない。alias は root にしかならない：構造上、循環は作れない） | |
| ID の再利用・alias の改名を拒否 | トリガー（alias と根拠 ID の名前の衝突を双方向に拒否、alias は追記専用） | |
| 同じ値でも別の case・年度・学部・募集枠は統合しない | case を強制 | **スコープ・fact_key・原典が違えば拒否**（独立した事実） |
| 内容の分類 | | `duplicate`（値も位置も同じ）と `same_value_moved`（値が同じで位置だけ違う）だけが alias。`independent`・`conflict` は拒否 |
| locator の訂正だけで新しい root を作らない | 既存の改訂経路（同じ logical id・case・fact_key の revision、`stage` が検査） | alias で表す |
| `UNIQUE(case,source,fact_key)` | **削除しない・変更しない** | locator を含める粒度の変更は別の契約（`WORK_CONTRACT_REVIEW_PENDING`） |

### 6 対応（実コピーの使い捨てクローンで確認）
`EV-G27C-01〜06-e1137e` を `EV-G27-01〜06-e1137e` の alias として登録：**01 は位置訂正後の現行版 `EV-U-8d8e1d177883` に解決**（旧 `EV-G27-01` の誤った位置へは向かわない）、02〜06 は各 root に解決。旧行・旧記事・履歴は不変。新潟 2 学部の `postal_period`（同じ値・同じ原典・別の学部）は **alias にできない**（コード層もデータベースも拒否）。

### 2.5 契約所有者レビュー（2026-11-07）：登録の証明・固定版・同時更新
詳細と判断表は `docs/G05_OWNER_REVIEW_2026-11-07.md`。要点（**Work の合意が要る：`WORK_CONTRACT_REVIEW_PENDING`。実装は `register_alias` に反映済みだが、Work の製品の登録経路の実装・M1.g1 の受容ではない**）：
- 別名の `case_id` は常に root から導出する。レコードが明示するなら、一致が必要。レコードは位置（`proofs` か `field_proofs`）を述べなければならない。学科が `NULL` のサイクルに限り、別名の学科は `None` か欠落を許す（G-04＝A）。
- **版指定のない別名は、head に解決する（維持）。**固定版（`pinned_evidence_id`）は、**承認済みの登録だけ**が行える：登録の時点で有効 head が承認された版のまま、固定はその版そのもの、レコードはその版と値と位置が完全に一致、改訂の無い root は拒否。例外は別名ごとで、root・case・`kind`・サイクルへ波及しない。
- 承認済みの登録は、`INSERT … SELECT … WHERE (head がちょうど 1 つ) AND (その head が承認された版)` の 1 文で書く（検査と書き込みの間に head が動いたら、何も書かず拒否）。root に head が 2 つ以上あれば、別名の解決は曖昧さの誤りで、黙って 1 つを選ばない。
- 承認の記録（誰が承認し、どこに保存するか）はユーザーの承認が要る（未決）。位置の対応の照合記録は Work の独立な再抽出（未了）。

## 3. 使い捨てコピーで確認する SQL（読み取りの preflight）
```sql
-- G-04：衝突の有無（1 行でも出れば適用しない）
SELECT university,faculty,COALESCE(department,''),admission_method,fiscal_year,count(*) FROM admission_cycles GROUP BY 1,2,3,4,5 HAVING count(*)>1;
SELECT case_id,round_name,COALESCE(entry_month,-1),scope_json,source_sha256,count(*) FROM admission_offerings GROUP BY 1,2,3,4,5 HAVING count(*)>1;
-- G-05：alias の名前が既存の根拠 ID と衝突しないこと／root が実在すること
SELECT alias_id FROM evidence_aliases WHERE alias_id IN (SELECT evidence_id FROM facts UNION SELECT evidence_id FROM evidence_revisions);
```
実行は `python -m src.db_contract.additive_schema <コピー>`（既定は読み取りだけ）。適用は `--apply --confirm-disposable-copy`（**使い捨てコピーのみ**）。

## 4. 検証の結果（`reports/db-audit/real_copy_additive_g04_g05_2026-11-01.json`）
- 合成 DB：28 試験（`tests/test_additive_schema.py`）。
- v06 の使い捨てクローン：8 成功・0 失敗（preflight、新しい物だけが増え旧行は不変・`db_audit` DB-09 pass、再実行で不変、G-04、衝突での停止、6 対応、独立した事実、負例）。
- **Work の更新経路は移行後のクローンでも動く**：g4 の harness（21 ケース）が移行後のクローンで **21 成功・0 失敗**。
- 限界：`SELF_VALIDATED`。Work の再レビューが要る。**未適用**（運用DB・原本・監査コピーのいずれにも）。

## 5. Work への依頼（`WORK_CONTRACT_REVIEW_PENDING`）
1. G-04 の同一性の単位（`exam_year` を含めない）と、offering の追加索引に同意するか。
2. G-05 の `evidence_aliases` の定義（root は `facts`、版の固定は改訂のみ）、旧 ID の alias 登録の内容（6 対応と、他にある旧 ID）に同意するか。
3. `UNIQUE(case,source,fact_key)` の locator 粒度の変更を、いつ・どう扱うか。
4. 合意後、Work が運用DBへ適用する手順（バックアップ→使い捨てコピーでの dry-run→原子的な適用→`db_audit`→g4 の harness で再確認）。**Claude は原本に適用しない。**
