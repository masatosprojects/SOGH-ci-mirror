# g3：履歴表の `INSERT OR REPLACE` 迂回 — 独立再現と契約提案の修正（2026-11-08）

立場：契約の所有者（`src/db_contract/historical_read.py` の `history_ddl` は私の提案）としての修正と、独立 QA としての負例。**契約提案レベルの修正であり、g3 の受容でも 0010／DB-17／DB-19 の登録でもない。保管先・承認方式・署名付き復元は決めていない。**
修正した作者本人の試験（SELF_TEST）であり、独立 QA ではない。Work など別担当の再試験を依頼する。

## 発端

Work（issue #55 コメント 6714222911）：既存の履歴 DDL 案は、`recursive_triggers=OFF`（SQLite の既定。接続ごとの設定で、表は要求できない）の接続で `INSERT OR REPLACE` により復元イベントの来歴が差し替わる。BEFORE INSERT のキー衝突ガード1件で拒否できた、他の履歴表と全一意制約は未確認。

## 独立再現（Work のコードを使わない。合成行、`:memory:`、SQLite 3.42.0）

SQLite は、REPLACE が衝突行を消すときに削除トリガーを動かすのは `recursive_triggers=ON` のときだけ（公式の挙動）。

| ガードの状態 | 全一意キー7経路（5表） | 明示した rowid（5表） |
|---|---|---|
| なし（現行提案） | **7/7 差し替わる** | **5/5 差し替わる** |
| なし、`recursive_triggers=ON` | 0（削除トリガーが動いて拒否） | 0 |
| **Work の試作：キー列だけを見る BEFORE INSERT** | 0（拒否） | **5/5 差し替わる** |
| キー列＋rowid を見る BEFORE INSERT（本修正） | 0 | 0 |

つまり Work の試作は、キー衝突は塞ぐが、**rowid を明示した `INSERT OR REPLACE` は全5表でまだ通る**（`INSERT OR REPLACE INTO t(rowid, …)` は、そのrowidを持つ行を、キーが何であっても置き換える）。`UPDATE OR REPLACE`、通常の `UPDATE`・`DELETE` は現行トリガーで拒否される。

## 修正（契約提案の中だけ）

- `history_ddl(append_only=True)` が、各表に `trg_<表>_no_replace`（BEFORE INSERT）を足す。既存のキー（主キー・UNIQUE）のどれかが衝突、または新しい行の rowid が既存の rowid と衝突するとき `RAISE(ABORT)`。新しい行の追記（rowid が空き）は通る。
- 一意キーの一覧 `HISTORY_UNIQUE_KEYS` を契約に持つ。SQLite が報告する実際の一意索引と一致することを試験で固定（キーを足して一覧を直し忘れると失敗）。
- `history_ddl(append_only=False)`（破損ファイルを作る試験用）は従来どおり何も足さない。

## 証拠

- `tests/test_g03_replace_guard.py`：42件（`recursive_triggers` の ON/OFF × `INSERT OR REPLACE`/`REPLACE` × 7 キー経路、rowid 5 表、通常追記と既存保護、キー一覧の整合、無保護版の不変、トリガー集合）。修正前のコードで21件失敗。
- 既存の `tests/test_g03_read_contract.py` 72件を含め 114 passed（Windows、Python 3.12.0）。
- 変異試験（使い捨てコピー）：8/8 検出（rowid 句の削除、キー1件の忘れ、複合キーの片側、トリガー未設置、AFTER INSERT への変更、無効化、UPDATE トリガー削除）。

## 影響

- Work の `probe_history_replace_matrix.py` と `probe_archive_binding.py` は `historical_read.py` の Git blob SHA（`ba89ccc8…`）を固定している。この修正でファイルが変わるため、**両ファイルの再固定が必要**（Work 所有。私は触らない）。
- 他の履歴系の表（#96 のアーカイブ表の保護、`evidence_heads` など）の `REPLACE` 経路は、この修正の範囲外。同じ手順で洗い出す必要がある（READY_INDEPENDENT）。
- 権限・署名のある更新経路、`DROP TRIGGER`／`DROP TABLE` を使う操作者は、トリガーでは防げない（正式な権限設計と署名付き復元の担当）。

## 追補：Work の独立QA（58cc52b、27 PASS／5 FAIL）への対応（2 回目の head）

Work（#261 コメント 6714903519、固定 `audit261.py`）：一意キー7経路・明示rowid・FK・競合・ロールバックは拒否または保全で PASS。FAIL は 5 件。

| 所見 | 原因 | 対応 |
|---|---|---|
| 4 表で NULL 識別子が通る（`restore_events`／`restore_revocations`／`restored_articles`／`evidence_history_versions`） | rowid 表では `TEXT PRIMARY KEY` だけでは NOT NULL にならない | 主キー列に `NOT NULL` を明記（契約提案の列定義。契約所有者の判断として実施） |
| 既存の rowid=-1 の行があると、新規キーの通常 INSERT まで拒否される | BEFORE INSERT では rowid を省略しても明示しても `NEW.rowid` が -1 になり、-1 を比較すると必ず衝突する | BEFORE INSERT では `NEW.rowid >= 0` のときだけ rowid の衝突を見る。負の rowid を持つ行は新たに作らせない（AFTER INSERT で `NEW.rowid < 0` を拒否。文は取り消され、置換された行も戻る）。既存の -1 の行があっても次の自動 rowid は 0 になり、追記は通る |

- `tests/test_g03_replace_guard.py` は 53 件（NULL 5 表、負の rowid、既存の -1 の行とその後の追記、rowid 0 の衝突を追加）。既存の読み取り契約72件と合わせて 125 passed。変異試験 15/15 検出。
- **同一行の再投入は拒否される**（キーが衝突するため）。これはガードの結果であって、「再投入は何もしない（no-op）」か「拒否」かという契約の決定ではない。冪等にしたい場合は書き込み側（挿入前の確認）で行う。契約としての決定は未了。
- **テーブルの型は変えていない**（`WITHOUT ROWID` にすれば NULL と rowid の問題は同時に消えるが、Work の検証が rowid を前提にしているため採っていない。採るかどうかは保管先の設計と一緒に決める事項）。

## 追補2：Work の独立再QA（92ec19e：旧32条件 32 PASS、追加 8 PASS／1 FAIL）への対応

Work の再QA（#261 コメント 6719051114、固定 `audit261_delta.py` @`88579cea`）：負の rowid を新規に作ることは5表とも拒否され、旧 rowid −1／−7 の差し替え拒否後も旧全行が保全された。FAIL は1件：**最大 rowid が −7 の旧表では、通常の追加で自動 rowid が −6 になり拒否される**（−1 の手順は妥当だが、一般の負 rowid の旧表を網羅しない）。適用対象を限定するか互換策を採るかは契約所有者の判断、とされた。

**評価**

- 履歴5表（`restore_events`・`restore_revocations`・`restored_articles`・`evidence_history_versions`・`article_history_pins`）を作るマイグレーションは master にまだ無く（`additive_schema` は `restored_articles` が存在すれば読むだけ）、実在のDBがこの状態になることはない。負の rowid を持つ旧表は、手作りの合成ファイルでしか起きない。
- 実DB・実コピーでの確認は、この記録の作成時点でできていない（NOT_RUN）。

**判断（契約として）**：互換策（負の自動 rowid を許す）は採らない。負の rowid を許すと、明示した負の rowid による差し替えを区別できなくなり、#261 の保護が弱まる。代わりに**既存ファイルへの適用前に拒否する条件**を契約に加えた。

- `history_preflight(db)`：**読み取り専用**。負の rowid を持つ行、キー列の NULL を理由つきで返す。何も変更・修復しない（読み取り専用接続でも動き、ファイルのハッシュは不変）。
- `history_guards_for(db)`：事前検査が空のときだけガードの SQL を**返す**（実行も書き込みもしない）。空でなければ `ValueError` で理由を示し、SQL を返さない。どのコピーにいつ適用するかは所有者の判断のまま。
- 対応が必要な旧表は、所有者が行を新しい表へコピーして正の rowid にした上で適用する（私はデータを変更しない）。

**証拠（SELF_TEST）**：合成DBのみ。`tests/test_g03_replace_guard.py` は 62 件、既存の読み取り契約と合わせて 134 passed。事前検査の部分の変異試験 6/6 検出。独立再QAは Work の再試験待ち。

## 追補3：Work の独立再QA（b6b582e：合成ファイル 5 PASS／2 FAIL）への対応

Work の再QA（#261 コメント 6719815576、固定 `g3_preflight_probe.py` @`e5f19b2b`）：負 rowid（−7／−9／正負混在）と NULL は拒否され、全7ファイルの SHA は不変。FAIL は2件：**履歴表が無いファイル、5表の一部しか無いファイルで、`history_preflight` が理由0（正常）を返し、`history_guards_for` が適用できない SQL を返す**（別の合成DBで実行すると失敗する）。

**原因**：事前検査が「存在する表だけを調べて、無い表は飛ばす」作りだった。ガードは5表すべてに依存するので、無い表は「問題なし」ではなく「適用不能」。

**修正（適用不能な SQL は返さず、そろっていない理由を明示して拒否する）**

- `history_preflight` が次を理由つきで報告する：(1) 5表のうち**存在しない表**（「この表が無い。ガードは5表すべてを前提にする。先に表を作る（0010／DB-17／DB-19の別の段階）」）、(2) **キー列を欠く表**（別のレイアウト）、(3) ガードのトリガーが**一部だけ**存在する半端な状態、(4) 従来どおり負の rowid と NULL のキー。
- `history_guards_for` は理由があれば `ValueError`（SQL は返さない）。**ガードが20個すべて既にある**ファイルには空文字列を返す（最初の重複で失敗する SQL を返さない）。
- 完全な5表の正常ケースは従来どおり実行可能な SQL を返す。読み取り専用接続・ファイルの SHA 不変・`total_changes == 0` も保たれる。

**証拠（SELF_TEST）**：Work の固定プローブ（7ケース）を新 head で実行：7/7 期待どおり（`complete_clean` は実行可能な SQL、その他6件は拒否で、全ファイル不変、理由の数は −7／−9／混在／NULL が各1、表なしが5、一部のみが4）。`tests/test_g03_replace_guard.py` は 68 件、既存の読み取り契約と合わせて 140 passed（旧い仕様「表が無ければ空」を表明していた試験1件は、意図した契約の変更として書き換えた）。事前検査の境界の変異試験 8/8 検出。

**未決・NOT_RUN**：実コピー・実DBへの適用（していない）、独立再QA（Work 待ち）。表を作る段階（0010／DB-17／DB-19）と、旧 −7 表の扱い（行を新しい表にコピーして正の rowid にする等）は所有者判断のまま。

## NOT_RUN

独立再試験、実コピー・実 DB への適用、正式 0010／DB-17／DB-19、状態B／F-2、署名付き復元、Linux・Python 3.11、GitHub Actions。M1 は 2/8 NOT ACCEPTED のまま。
