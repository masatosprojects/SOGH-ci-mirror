# M1.g5 移行履歴の検出関数：独立QAへの引き渡し（PR #268、2026-11-08）

**この文書は、作者（Claude）から独立レビュアー（Work または Antigravity）への引き渡し。作者の試験は SELF_TEST であり、独立QAではない。** 受容でもマージの依頼でもない。M1 は 2/8 のまま。

## 1. 対象

- ブランチ `claude/g5-migration-history-checks`（Draft PR #268）。固定 head は PR と #199 の報告に記載。
- 変更：`src/db_contract/additive_schema.py` に**追加のみ**の4つの関数と1つの定数。
  - `verify_history_provenance(db) -> list[str]` 読み取り専用・検出専用
  - `history_witness(db) -> tuple[tuple, ...]` 読み取り専用
  - `verify_history_step(before, db, *, expected_new=None) -> list[str]` 読み取り専用・検出専用
  - **`verify_history_for_acceptance(db, *, before, expected_new=None, through=None) -> list[str]`** 読み取り専用・検出専用。**受容の判定に使ってよいのはこれだけ**（下記）
  - `HISTORY_COLUMNS`

**重要（独立QA #272 / 91abc70 の指摘への対応）**：履歴表が無い DB に対して、旧い版の3関数は `[]`／`()`／`[]`（理由なしの正常）を返した。「`not verify_history_provenance(db)` なら受容」と判定すると、未移行・消去済みの DB が誤って受容される（False-Pass）。現在は、**履歴表が無い・行が0件・別レイアウトのときは理由を返す**。それでも `verify_history_provenance` と `verify_history_step` は「ある行の整合」を見るだけで、**0002〜0009 がそろっていること**は言わない（0004 で止まった履歴も整合している）。**完全性は `verify_history_for_acceptance` だけが見る**：履歴が連鎖と一致、既存の契約（`verify_history`・`verify_schema_state`）、来歴、事前証拠との照合のすべてが成り立ったときだけ `[]`。事前証拠 `before=None` は理由、空の証拠は `expected_new` が無ければ理由。既存の `verify_history` は**変更していない**（`apply()` が履歴の無い DB を移行するために `[]` を返す契約に依存しているため）。
- **変更していない（合意なしに変更しないこと）**：`apply()`・`plan()`・`verify_history`・`verify_schema_state`、凍結SQL 0002〜0009、`db_audit`・`real_copy_additive_audit`（g4・g8 の受容済みの経路）。新しい関数はこれらのどこからも呼ばれない。
- 実DB・実コピーには触れていない。試験は、ランナー自身が作った使い捨てコピー（`tests/db_support.make_native` ＋ `additive_schema.apply`）だけ。

## 2. 各関数の契約と、固定した期待値

| 呼び出し | 期待 | 固定した試験 |
|---|---|---|
| ランナーが作った DB に `verify_history_provenance` | `[]` | `test_H1`、`test_H2`（1回目と別の実行に分けても） |
| `from_version` を置換（rowid 保持） | `says it follows '…'` | `test_H3` |
| `description` を置換 | `description that is not the one this code holds` | `test_H3` |
| `applied_at` が後ろの行より未来 | 次の行に `before the migration applied just before it` | `test_H3` |
| `applied_at` が時刻でない／時区なし | `not an ISO-8601 time`／`without a time zone` | `test_H3` |
| 同じ内容を行ごと書き直す（rowid が末尾になる） | 1件：`written again after the later ones` | `test_H3b` |
| NULL の版、非正の rowid | `has no version`／`rowids are positive` | `test_H5` |
| rowid を保ち、前後の間の時刻に置換 | `verify_history_provenance` は **`[]`（既知の限界）**。`verify_history_step` は `changed its applied_at` | `test_H4` |
| 旧行のどの列を変えても | `verify_history_step` が `changed its <列名>` | `test_H6`（7列） |
| 旧行の欠落／飛んだ版／前版の偽り／連番の誤り／先頭より前の連番／`user_version` の据え置き | 各々の理由 | `test_H7` |
| `expected_new` | 厳密一致のみ | `test_H8` |
| 読み取り専用接続・ファイルのハッシュ不変 | 動作する・不変 | `test_H9` |
| 履歴の表が無い | provenance／step は**理由を返す**（`does not exist`）。`history_witness` は `()`（値であって判定ではない）。`verify_history` は `[]` のまま（既存の契約） | `test_H10` |
| 履歴の表が空（行0件）／別レイアウト | provenance は理由（`holds no migration`／`another layout`） | `test_H14`、`test_H12` |
| **受容ゲート**：完全で、証拠と一致する履歴 | `verify_history_for_acceptance` は `[]`（新規の移行は `before=()` かつ `expected_new=<全連鎖>`） | `test_H13` |
| 受容ゲート：表なし／空／外部のDB | 理由（`does not exist`／`holds no migration`／`not the complete chain`）。正しい `expected_new` を渡しても通らない | `test_H14` |
| 受容ゲート：一部だけの履歴（行は整合している） | 理由（`not the complete chain: N of …, missing …`）。`through=` で止まる位置を明示した場合のみ受理、多すぎも理由 | `test_H15` |
| 受容ゲート：履歴を消去した DB | 理由（空の履歴・`is gone`・連鎖不一致）。空の証拠を渡しても通らない | `test_H16` |
| 受容ゲート：証拠なし／空の証拠 | `no witness was given`／`an empty witness proves nothing…` | `test_H17` |
| 受容ゲート：行の改ざん・チェックサム変更 | 理由（`description`／`checksum mismatch`） | `test_H18` |
| 受容ゲート：別レイアウト、読み取り専用 | 別レイアウトは理由。読み取り専用接続で動き、ファイルのハッシュ不変 | `test_H19` |
| 既存のランナーと `verify_history` | 変更なし | `test_H20` |
| 別レイアウトの `schema_migrations`（PR #70 の下書き型） | provenance は理由1件、`history_witness` は `MigrationError`、`verify_history_step` は理由 | `test_H12` |
| 既存の `verify_history` | 変更なし（description の置換は見ない） | `test_H11` |

再現：リポジトリのルートで `python -m pytest tests/test_g05_history_provenance.py`（31件）。既存の回帰：`tests/test_additive_schema.py`・`test_g09_and_runner.py`・`test_guard_migration.py`・`test_frozen_migrations_*_record.py`・`test_f2_archive_db17_prototype.py`・`test_pr96_sql_candidate_review.py`（98件）。

作者の変異試験：30件の変異（各検査の削除・無効化）をすべて試験が検出した（使い捨てコピー）。初回は私の試験が弱く7件が生き残ったため直した。変異スクリプトは作者の作業用で、リポジトリには含めていない。

## 3. 既知の限界（直していない・隠さない）

1. **rowid を保ち、もっともらしい時刻と正しい連鎖で行を置換されると、DB内の検査（`verify_history_provenance`）は検出できない**。検出できるのは、移行前に DB の外へ保管した証拠との照合（`history_witness`／`verify_history_step`）だけ。**証拠をどこに・誰が保管するかは運用の決定で、未決。**
2. `verify_history_step` は列の値を比べる。行の物理的な位置（rowid）は比べない（`test_H3b` で、同一内容の書き直しは provenance だけが検出し、witness は検出しないことを固定した）。
3. 防止はしない。`schema_migrations` を守る挿入前ガード（凍結SQL 0004 の変更または新しい移行）は**提案のみ**（`docs/M1_G3_G5_CONTRACT_STATUS_2026-11-08.md` の C3）。
4. 最初の行の `from_version` は「最初の移行の前に `schema_versions` が言っていた事実」で、後から検証できない。
5. `applied_at` は ISO-8601 で時区が必要。`Z` 接尾辞は Python 3.11 以降で解釈される（3.12.0 で確認、3.11 は未確認）。

## 4. 独立レビュアーに特に確認してほしい負例（作者の試験が覆っていない）

- WAL モードのファイル、および `-wal`／`-shm` が残るコピーでの動作。
- 実在する v06 のコピー（Work 提供）での `verify_history_provenance` の結果。**既存の実コピーに偽陽性が出ないか**が最も重要（出る場合は、検査が過剰か、過去の移行が別の経路で書かれたのかを切り分ける）。
- `apply(only=…)` を複数回に分けた履歴、`+09:00` など UTC 以外の時区を持つ手書きの `applied_at`。
- 非 ASCII を含む `description`、`seq` の重複や負数、`version` の大文字小文字違い。
- 作者の見落としの探索：置換以外の経路（`INSERT OR IGNORE`、`ATTACH` した別ファイル、`PRAGMA writable_schema`）。

## 5. 判定の仕方（独立QAとして）

- PASS／FAIL／NOT_RUN で報告し、**作者の試験の結果を独立QAの結果として数えない**。作者の変異試験の結果も同様。
- FAIL が出たら、固定入力・期待値・観測値・重要度を #268 にコメントしてください。作者は根本原因に最小の修正をして、固定 head を更新します。
- PASS でも、作者はマージも受容もしません（Work の統合レビューとユーザーの判断）。
- **受容の判定を実装する側（将来の `apply()`／`db_audit` への組み込みを含む）は、`verify_history_for_acceptance` を使うこと。`verify_history_provenance`・`verify_history_step`・`verify_history` の『理由なし』を、受容として扱わない。**
