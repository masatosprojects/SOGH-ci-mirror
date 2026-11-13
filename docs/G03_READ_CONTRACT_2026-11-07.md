# M1.g3 正式読み取り契約（旧記事・旧根拠版）— 契約所有者の確定案（2026-11-07、Claude）

対象：Issue #55 の Work の報告 [6688143094](https://github.com/masatosprojects/SOGH-collab/issues/55#issuecomment-6688143094)（合成回帰・候補 12 件）、[6688493523](https://github.com/masatosprojects/SOGH-collab/issues/55#issuecomment-6688493523)（F-2 の来歴対応表・7 項目）、[6697130183](https://github.com/masatosprojects/SOGH-collab/issues/55#issuecomment-6697130183)（`work/m1-read-connection-probes` `bcea29d444421c90c57b06980659be4c551ef363`、現行 `export_active.py` が 3 PASS／4 FAIL）。固定：`master` `88c2fedd6e26a836bf2930c9c8d010a719dc8b4f`、F-2 = PR #96 `aa3032649106eb0bb02fb8ab864fae75d938e11c`。
**状態：契約の確定案（`CONTRACT_PROPOSAL`）と、その参照実装・合成試験（`SELF_VALIDATED`）を提出した。Work の製品経路への接続、正式復元、保管先の移行（0010／DB-17／DB-19）、F-2 のユーザー受容は未了。M1.g3 は PASS ではない。M1 は 2/8、NOT ACCEPTED のまま。**
実 DB・原本・本番には触れていない。合成 DB のみ。Work のコードは変更していない（`src/db_contract/` は Claude 所有）。

## 1. 独立に再現した事実

| 項目 | 結果 |
|---|---|
| Work の `probe.py`（`bcea29d`）を、`master` `88c2fedd` の `export_active.py` 2 か所（`work-faq-v3`、`work-updates-v2`。**同一の blob**）で再実行（Windows、Python 3.12.0、隔離の作業領域） | **3 PASS／4 FAIL を再現**：通常・値違い・原典 SHA 違いは拒否または受理が期待どおり。**同一原典の位置違い、case 違い、scope 違い、記事に結び付かない引用は通過（FAIL）**。2 接続の合成トランザクション 3 件は PASS（Work の合成であり、製品の `register_alias` の結果ではない） |
| 原因（`export_active.py` を読んで確認） | 比較するのは `fact_key`・`value`・`source_pdf_sha256` と、レコードに**書かれている場合の**大学・学部・学科・方式・年度のみ。**`case_id`、`scope`、位置（`locator`／`proofs`）、記事と根拠の関係（`article_evidence`）は一度も読まない**。さらに head を基の出力に**上書き**する。つまり旧記事を渡しても現行の根拠が表示される構造である |
| `export_active.py` の SHA-256 | 私の測定：`30b36e45de0fd81215378e8f8783752f63d2ee81cc1a17bb3d9b2d8fd44f8198`（`master`・`work/m1-read-connection-probes` とも同一）。**Work の報告 `c6c1b6a0…` と一致しない。原因は UNKNOWN**（別の表現のハッシュか別のファイルか）。Work は対象バイトを特定して訂正してほしい |
| 評価 | 現行の `export_active.py` は**現行ビューの出力**であり、旧版読み取りの入口ではない（Work の結論に同意）。同時に、**現行ビューの出力としても** case・scope・位置・関係の検査が欠けている（下の §6 の REVISE） |

## 2. 契約の一文

**記事が引いた根拠は、その記事が書かれた版そのものとして、1 つの入口で、1 つの読み取りスナップショットから、型と来歴つきの 1 つの値として返る。表示・出力はその値だけを使い、現行の根拠を二度目に引かない。足りない・食い違うものは、1 つでも「読めない」であり、現行の版への置換や格下げは決してしない。**

## 3. 型と入口（参照実装：`src/db_contract/historical_read.py`）

入口：`read_cited_evidence(db, article_id, evidence_id, *, expect=None, require_restored=None) -> CitedEvidence`（読み取りのみ、書き込み 0、書き込み権限不要、`mode=ro` の接続で動く）。

| フィールド | 内容 |
|---|---|
| `kind` | `current_citation`（通常記事）／`restored_history`（正式復元記事）。**経路はデータベースが決める**（`restored_articles` への登録）。呼び出し側の指定や自動の切り替えでは決まらない |
| `article_id`・`evidence_id`・`case_id` | 記事の版 ID、記事が引いた根拠 ID、記事の case |
| `version_id` | 復元の場合は保管された旧版の ID。通常は `None` |
| `scope` | 明示された適用範囲。**未記入・`UNKNOWN`・空は拒否（推定しない）** |
| `source_sha256` | 原典 SHA（行・版・固定で一致を要求し、`source_documents` に登録済みであること） |
| `row`・`row_digest` | 旧行そのもの（`evidence_id`・`case_id`・`fact_key`・`source_sha256`・`value_json`・`record_json` の保存済み文字列）と、その正規化 JSON の SHA-256。**位置（`locator`／`proofs`）は `record_json` の内側にあるので、位置違いはダイジェスト違いになる** |
| `provenance` | 復元の場合：`restore_id`・`archive_sha256`・`source_db_sha256`・`approved_by`・`approved_at`・`approval_ref`・`archive_row_sha256`。通常は `None` |
| `bound_digest` | 上の識別子と来歴を束ねたダイジェスト。出力側が改ざんを検出するために使う（`verify_export`、DB なしで検証できる） |

**`expect`（任意）**：消費者（出力側）が自分の記録として持つ `case_id`・`scope`・`source_sha256`・`row_digest`・`record_subset`（位置など）。1 つでも違えば `expectation_mismatch`。Work の 4 FAIL は、すべてこの入口と引用関係の検査で拒否される（試験あり）。

**拒否の符号（27 種、すべて試験）**：`bad_input`・`article_unknown`・`cycle_unknown`・`citation_missing`・`citation_duplicated`・`registry_ambiguous`・`registry_inconsistent`・`schema_unavailable`・`restore_unavailable`・`pin_missing`・`pin_duplicated`・`history_version_missing`・`history_version_duplicated`・`row_malformed`・`digest_mismatch`・`binding_mismatch`・`case_mismatch`・`source_mismatch`・`source_unregistered`・`scope_unknown`・`scope_mismatch`・`current_evidence_missing`・`evidence_ambiguous`・`not_restored`・`restored_article_on_ordinary_route`・`expectation_mismatch`・`export_tampered`。

## 4. 保管先の提案（0010／DB-17／DB-19 が最終形を決める。**移行は未実装、どの DB にも未適用**）

`HISTORY_DDL`（追記専用のトリガーつき）：`restore_events`（復元の事象と承認：承認者・承認日時・承認の参照・アーカイブと元 DB の SHA）・`restore_revocations`（取り消し。取り消された復元は読めない）・`restored_articles`（**復元記事の登録。これが経路を決める**）・`evidence_history_versions`（旧版の行。`row_digest` は一意、`archive_row_sha256` で F-2 のアーカイブ行へ追跡）・`article_history_pins`（記事×根拠 → 旧版、case・scope・原典 SHA・ダイジェストを記録）。
**既存の行・ID・引用関係・互換出力は一切変えない**（追加のみ）。旧い根拠版は `facts` に戻さない（同じ ID に別内容が既にあるため）。

## 5. 7 項目の確定（ACCEPT／REVISE／BLOCKED）

| # | 項目 | 判断 | 契約・条件 | 試験 |
|---|---|---|---|---|
| 1 | 通常記事の現行引用 | **ACCEPT** | 復元の記録を要求しない。履歴の表が無い DB でも動く。引用された ID の行をそのまま返し、head を追わない。既存の `cited_version` と同じ根拠 ID を指す | item1 ×3 |
| 2 | 正式復元記事の固定版の読み取り | **契約 ACCEPT／保管先 BLOCKED** | 復元の登録 → 事象（取り消しなし）→ ピン 1 件 → 旧版 1 件 → ダイジェストの再計算 → 全項目の一致、をすべて満たしたときだけ返す。旧い行（値 16・原典 A・p.6）を返し、現行の行（値 20・原典 B・p.8）は返さない。保管先は 0010／DB-17／DB-19 と F-2 のユーザー受容が前提 | item2 ×2 |
| 3 | 旧版・対応の欠落 | **ACCEPT** | 版・ピン・事象・引用の欠落、取り消し、重複はすべて拒否。**現行行で埋めない。復元記事を通常記事に格下げしない**（登録があるのに履歴表が無い → `schema_unavailable`、ピンがあるのに登録が無い → `registry_inconsistent`）。旧 `cited_version` は復元記事を拒否する（今回の変更） | item3 ×約 20 |
| 4 | 同じ ID で値・本文・原典・版が違う | **ACCEPT** | 行ダイジェストを**再計算**し、保存値・ピンの値と 3 者一致を要求。位置だけの違い（同じ原典）も拒否。別の根拠 ID の版へのピン、別の復元事象のピンも拒否。**原典 SHA が同じでも旧版は特定できない**（Work の実測：旧根拠 5 件のうち値が変わったのは E4 のみだが、行全体のダイジェストは 5 件とも相違）ので、SHA を加えるだけの識別は不可 | item4 ×約 14 |
| 5 | case／scope の不一致 | **ACCEPT（形）／意味の同一性は BLOCKED** | 記事・ピン・保存版・レコードの case が一致、scope は明示かつピンと一致、サイクルの次元（大学・学部・学科・方式・年度）がレコードにあれば一致。**未確定の scope は推定しない。G-05 の 01 の例外（固定版）を流用しない**。scope ラベルが原典の意味と合うかは、原典の再照合（Work：NOT_RUN／UNKNOWN）が復元の承認の前提 | item5 ×約 20 |
| 6 | 読み取り途中の head 更新 | **ACCEPT（参照実装）／製品経路 NOT_RUN** | 1 回の読み取りは 1 つのトランザクション（呼び出し側が持っていればそれを使い、触らない）。復元の取り消し・ピンや版の削除・現行 fact の変更・head の移動を、読み取りの**あらゆる地点**に差し込んでも、結果は変更前と同一（WAL）か、書き込みが拒否される（ロールバックジャーナル）。混在は起きない。取り消しの後の**新しい**読み取りは拒否 | item6 ×4（2 モード×22 地点） |
| 7 | 表示・出力への伝搬 | **契約 ACCEPT／消費者の接続は BLOCKED** | 消費者は `CitedEvidence`（または `to_export()` の辞書）だけを使う。版・原典・来歴・scope・ダイジェストは出力に残り、`verify_export` で DB なしに検証できる（値・原典・版・承認者・scope・case・種別・欠落・余分な項目の改ざんを拒否）。**再取得の禁止は `forbid_current_evidence_reads` で SQLite 自身が拒否する形で検証する** | item7 ×約 20 |

### 旧記事の固定根拠を検証した後、表示・出力側が現行根拠を再取得しないこと（受容条件）
1. 表示・出力の工程を `forbid_current_evidence_reads(db)` の中で実行する。この間、根拠・履歴・関係・復元の表とビューへの**あらゆる読み取り**が拒否される。工程が通れば、読み取りの結果だけを使っている。
2. 同じ工程に「ID で `facts` を再取得する」実装を入れると拒否される（試験で実証。この道具が無ければ、その誤りは現行値 20 を黙って表示する）。
3. 出力ファイルは、`verify_export` を DB なしで通ること。

## 6. 引き渡し

### Work が契約合意後に直ちに実施できること（追加の承認は不要）
- 現行ビュー用 `export_active.py` に、case・scope・位置（行ダイジェスト）・記事との関係の検査を足す（**REVISE。Work のコード。4 FAIL が 4 PASS になること**）。Claude の `expect` と同じ意味で足せば、二重実装を避けられる。
- 出力側の消費者を `read_cited_evidence` に接続する試験を、**隔離コピーと合成 DB**で用意する（接続は `CitedEvidence` を渡す形。`export_active` の流用は禁止）。`forbid_current_evidence_reads` の中での表示・出力、`verify_export` の往復を含める。
- 復元用の道具の**設計**（F-2 の archive 行から `evidence_history_versions` を生成する手順、`archive_row_sha256` の突合）。**実 DB への書き込みは含まない。**
- 隔離試験の負例：下の §7。

### 追加の承認を要すること（ユーザー）
- 保管先の移行（0010／DB-17／DB-19）の確定と適用、F-2 の正式復元（`restore_events` の承認者・承認の置き場）、旧版の原典・scope の意味の再照合の承認、本番・実コピーへの適用。**Claude／Work は実行しない。**

## 7. 隔離試験の負例（Work が自分の経路で実行する。参照実装の試験が見本）
欠落（版・ピン・事象・引用）／取り消し／重複（ピン・版・登録・事象・引用）／値・位置・原典・キー違い（同じ原典を含む）／別根拠 ID・別復元事象のピン／case 違い（記事・ピン・版・レコード）／scope 未記入・`UNKNOWN`・ピンとの不一致・サイクル次元の不一致／`expect` の各項目の不一致／通常記事の他 case の根拠／**読み取り中の変更（取り消し・削除・fact の変更・head の移動）の差し込み**／出力の改ざん／再取得／復元記事を通常の入口で読む／ピンだけあって登録が無い。

## 8. 独立 QA の完了条件（M1.g3 を PASS にするために）
1. 状態 B と旧版の保管先（0010／DB-17／DB-19）の契約が合意され、ユーザーが承認していること。
2. **隔離コピー**に対し、Work の製品の経路が `read_cited_evidence` 相当の契約を満たすこと（§7 の負例のすべてと、通常記事の互換）を、**Claude の独立試験**で確認（入力の SHA・コードの head・環境・実行者・結果を記録。Work の自己試験・Antigravity の自己試験は代替にならない）。
3. F-2 の来歴対応表（旧記事 6 版・引用 24 件・旧根拠 5 件・値の相違は E4 のみ）を、固定 SHA の入力（v03・v06・アーカイブ）から**独立に再計算**して一致すること。**今回は入力の写しが手元に無く NOT_RUN**。
4. 表示・出力で、再取得禁止の検査と `verify_export` が通ること。読み取り途中の更新の 2 接続の試験を**製品の経路で**実行すること（今回：参照実装のみ。製品は NOT_RUN）。
5. F-2 のユーザー受容。

## 9. 参照実装の限界（正直な記録）
- 行・版・ピンが**互いに整合するように偽造**された場合、リーダーはそれを検出できない（ダイジェストは自己整合を見るだけ）。防ぐのは、復元の承認（`restore_events`）と、`archive_row_sha256` を F-2 のアーカイブの行と突合する復元の道具（Work）、およびその独立 QA である。
- 合成 DB の列は実テーブルの定義に合わせたが、実コピーでの動作（実在の `record_json` の形、`scope` の記録の有無）は**未確認（NOT_RUN）**。通常記事の経路は `scope` を要求しない（実データの既存記録を誤って拒否しないため）。
- 保管先のテーブル名は提案である。0010 で変わった場合は、リーダーとテストを追随させる。

## 10. 依存の整理
| 依存 | 関係 |
|---|---|
| 0010／DB-17／DB-19 | 保管先（`HISTORY_DDL` の正式化）。**BLOCKED（ユーザー承認）** |
| F-2（PR #96） | 旧版の素材（アーカイブ行）と来歴対応表。ユーザー受容待ち |
| G-05 | 根拠 ID の空間。**01 の固定版の例外は流用しない**（PR #191） |
| G-07 | `cited_version`・関係表（既存。復元記事は旧関数で読めない形に） |
| G-09 | 追記専用・head の整合（履歴表も追記専用の提案） |
| G-11 | 理由・訂正の記録（復元の承認の記録は別だが、同じ追記専用の原則） |

## 11. 試験
`tests/test_g03_read_contract.py`（合成のみ）。変異の検査は PR 本文に記録。M1 は 2/8、NOT ACCEPTED。
