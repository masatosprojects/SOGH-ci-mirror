# M1.g3・g5：Claude 所有の契約の整理（2026-11-08）

立場：DB契約の所有者。**契約の状態表であり、受容でも決定でもない。** M1 は 2/8（g4・g8）NOT ACCEPTED のまま。根拠は最新 master `b0d5635c…`（`docs/DB_COMPLETION_DASHBOARD.md` と各契約文書）。実DB・実コピー・本番には触れていない。保管先と承認方式は決めていない。
自分のコードの試験は SELF_TEST。他者（Work・Antigravity）のコードへの確認は別に「独立QA」と明記する。

## 1. g3（旧版の保全と影響の追跡）：何がどの状態か

| 項目 | master で実装済み | 提案のみ（未マージ） | 合成DBでの確認 | 実DBコピーへの適用・独立QAが必要 | 未決（所有者・ユーザー） |
|---|---|---|---|---|---|
| 追記専用の保護（G-09、0004） | 凍結SQL 62文、ランナー、スキーマ状態検査（`SELF_VALIDATED`） | — | `test_guard_migration` ほか | 実コピーへの適用と DB-09（更新前後の比較）。Work の契約合意（`WORK_REVIEW_PENDING`） | 運用DBへの適用の承認（ユーザー） |
| 改訂記事→根拠の版（G-07、0005）／改訂の理由（G-11、0006） | 凍結SQL | — | 合成で確認（`SELF_VALIDATED`） | 同上（実コピーで v05→v06 の再実行） | Work の合意、適用の承認 |
| 正式な読み取り契約（旧記事・旧根拠版） | `read_cited_evidence`（#193、master）、Work の消費側（#207、master）、区分・範囲・位置の検査 | — | 合成で確認 | Work の製品経路への接続と、実DBコピーでの独立QA | 履歴の保管先に依存 |
| 復元履歴の保管先（5表：`restore_events` ほか） | なし（どのマイグレーションも作っていない） | **#261**（`history_ddl` の追加の保護、事前検査）。Work の独立再QA待ち | 合成で確認（62件、変異6/6） | 実コピーへの適用、DB-17／DB-19 の独立QA | **保管先（0010／DB-17／DB-19）の形、`WITHOUT ROWID` にするか、再投入の扱い（拒否かno-opか）** |
| F-2 アーカイブの正式統合 | 承認マニフェストの検証器（`approval_manifest.py`）、署名の補助（`scripts/sign_restore_approval.py`） | `F2_G2_MIGRATION_AND_DB17_CONTRACT`（追加の移行 `0010` と DB-17 の登録。試作18件） | 試作で確認 | Work の #96 の隔離コピーへの適用、独立QA | F-2 の説明と受容、**ユーザー本人の署名**（承認マニフェストが出てから） |
| 移行履歴 `schema_migrations` の改ざん耐性 | 追記専用トリガー（更新・削除）、`verify_history`（チェックサム・連番・`user_version`） | **本変更**：来歴列の検出と、事前証拠との照合（§3）。`schema_migrations` 自体へのガードは凍結ファイルの変更になるので**提案のみ** | 合成で確認 | 実コピーでの確認 | 凍結ファイルを変えるか、検出だけにするか（Work と所有者） |

### g3 の正式受容を阻んでいる未決（ダッシュボードと契約から）
1. v03→v04 の履歴破壊の説明（Work）と、開発途中DBの上書きとして受容するかの判断（ユーザーまたは Work）。
2. G-07・G-09・G-11 の運用DBへの適用：Work の合意とユーザーの承認が先。
3. 復元履歴の保管先と、再投入の扱い（#261 の未決）。
4. F-2 の説明、状態 B の復元、受容：ユーザー本人の署名つきコミットが必要。**私は署名を代行しない。**
5. 実DBコピーでの DB-09（更新前後）と DB-05/06/07：Work の実コピーの提供。

## 2. 現在の履歴を損なわない最小の追加型契約

| 番号 | 内容 | 状態 | 所有 |
|---|---|---|---|
| C1 | 復元履歴5表の追加保護（全一意キー＋rowid の置換拒否、NULL・負のrowidの拒否）と、既存ファイル向けの読み取り専用の事前検査 | #261（実装・自己試験済み、独立再QA待ち） | Claude |
| C2 | 移行履歴の**来歴列の検出**（`verify_history_provenance`）と**事前証拠との照合**（`history_witness`／`verify_history_step`）、および**受容の判定に使ってよい唯一の関数** `verify_history_for_acceptance`（履歴が連鎖と一致・既存の契約・来歴・事前証拠のすべてが成り立つときだけ空。履歴なし・空・一部だけ・証拠なしは理由）。検出専用で、凍結SQL・`apply()`・受容済み監査には**組み込まない** | 本変更（実装・自己試験済み） | Claude |
| C3 | `schema_migrations` の挿入前ガード（既存の `version`・`seq`・rowid の衝突拒否、負のrowidを作らせない） | **提案のみ**（凍結0004の変更または新しい移行が要る） | Work の確認・所有者判断 |
| C4 | C2 の組み込み先：`apply()` の事前検査、`db_audit` への項目の追加 | **提案のみ**（g4・g8 の受容済みの手順に影響するため、合意前には入れない） | Work と所有者 |

## 3. g5（過去データを失わず新スキーマへ移行）：確認した項目

| 確認項目 | 既存の保証 | 本変更で足したもの | まだ無い／要る |
|---|---|---|---|
| `schema_migrations` の存在・列 | G-02 のランナー（`version`・`from_version`・`applied_at`・`checksum`＋`description`・`seq`・`statements_applied_sha256`・`applied_statement_ids`） | — | — |
| 連続する版番号 | `verify_history`：適用済みが連鎖の先頭からの接頭辞であること（欠番・飛び・順序違い）、`seq` が版番号と一致 | 追記の一歩ごとに「次の版・連続する `seq`・正しい `from_version`」であることの照合（`verify_history_step`） | — |
| チェックサム | `verify_history`（凍結ファイルのバイト列のSHA-256との一致） | — | — |
| 旧行の不変性 | 更新・削除トリガー、DB-09（更新前後のコピーの比較） | 全列の照合（`history_witness`）。**DB外に保管した事前証拠が要る**ことを明記 | 事前証拠の保管方法（誰が・どこに）は運用の決定 |
| `user_version` | `verify_history`：最後に適用した版の連番と一致 | 一歩ごとの照合に同じ検査を含める | — |
| NULL／負のrowid | （履歴5表）#261 | `schema_migrations` の NULL の版、非正のrowid、物理順と `seq` 順の食い違い | 防止（C3）は提案のみ |
| 来歴列（`from_version`・`applied_at`・`description`） | **検出されていなかった**（独立走査 `a2e1e79`） | `from_version` の連鎖、`description` のコード側との一致、`applied_at` の形式・時区・単調性 | rowid を保ち、もっともらしい時刻と正しい連鎖で置換する者は、データベース内だけでは検出できない（事前証拠でのみ検出） |
| 互換性の事前検査 | #261（履歴5表） | `verify_history_provenance` が空であることを、既存ファイルでの「構築されたまま」の確認に使える | 実コピーでの確認は未実施 |

### 既存の migration・Work 担当コードとの依存
- `apply()`・`plan()`・`db_audit`・`real_copy_additive_audit` は `verify_history`／`verify_schema_state` を使い、g4・g8 の受容の手順の一部。**これらは変更していない**。新しい関数はどこからも呼ばれない（試験からのみ）。
- 凍結SQL（0002〜0009）は変更していない。Work の `migration_witness.py`・`migration_append_probe.py`（`work-preview-m1-cycle-02`／`work-preview-01-acceptance`）が読む `SCHEMA_MIGRATIONS` と凍結SQLは変更していない（それらの再実行はしていない）。C2 は、Work がすでに試作した「既存行の完全一致と、許可された次の1件の追加を分ける」照合を、契約の関数として明文化したもの。
- Work 所有のコードには触れていない。

## 4. 証拠（SELF_TEST）と NOT_RUN

- `tests/test_g05_history_provenance.py` 22件（実際にランナーで作った使い捨てコピー。来歴列ごとの単独検出、rowid を保った置換、同一内容の再書き込み、NULL・負のrowid、事前証拠の全列照合、欠落・飛び・誤った前版・誤った連番・`user_version`、読み取り専用接続でのファイル不変）。変異試験 16/16 検出（途中で試験の弱さを2回直した）。既存の移行系・凍結SQL・F-2試作・PR #96レビューの回帰試験 98件も通過（全体試験は流していない）。
- NOT_RUN：独立QA、実DB・実コピーへの適用、`apply()`／`db_audit` への組み込み、GitHub Actions、全体試験（変更部分と回帰試験のみ実行）。
