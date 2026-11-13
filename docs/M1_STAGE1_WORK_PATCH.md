# M1 段 1：Work の更新経路のパッチ案（Claude の代行、2026-11-01）

**ラベル：`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用への適用）。** 根拠：`docs/architecture/M1_SAFE_MIGRATION_PLAN.md` §1 の段 1、ユーザーの 2026-11-01 の指示（Work 一時代行、隔離ブランチ、運用DB不変）。**Work の配布物（`research/inbox/`）・ブランチ・原本・監査コピーは変更していない。** パッチは `patches/m1-stage1/work-pipeline-stage1.patch`（`research/inbox/work-faq-v3/pipeline` に対する差分）として置き、試験は**一時ディレクトリのコピー**にだけ適用する。Work は復帰後にこの差分をレビューして取り込む（またはより良い形で自分で実装する）。

## なぜ先に要るか
承認済みの設計（方式 B）では、DB 側が ①書き込み権限の関数 `sogh_write_ok` を呼ぶトリガー、②承認済み batch の改訂だけを head に許す規則を持つ。配布済みの Work のコードは、関数を登録せず、`finalize` が head を書いてから batch を approved にするため、**DB 側を先に適用すると更新経路が壊れる**（再現済み：`recover_candidates` が `no such function: sogh_write_ok`、`finalize` が承認済み規則で拒否）。

## 変更（3 ファイル、追加 約 30 行）
| ファイル | 変更 | 設計の根拠 |
|---|---|---|
| `store.py` | `configure_connection(db)`：能力関数 `sogh_write_ok` の登録、`PRAGMA recursive_triggers=ON`、`foreign_keys=ON`。`EvidenceStore.connect()` が使う | M-01・M-04 |
| `generic.py` | `promote_candidate` の接続（main へ併合する別接続）にも `configure_connection` | 全書き込み経路（M-04） |
| `revisions.py` | `finalize`：**batch を approved にしてから** head を動かす（同一トランザクション内の文の並べ替え。文自体は同じ）。`finalize(..., reason=None)` と `_record_reason`：呼び出し側が渡した理由だけを `revision_reasons` に書く（推測しない。表が無いのに理由が渡されたら失敗して全体を戻す） | M-02・M-13 |

`rollback_batch` は変更不要（head を削除→再挿入→最後に `rolled_back`。M-03 と同じ順序）。`recover_candidates`・`stage` も不変。

## 書き込み経路の棚卸し（配布版 2026-11-01、`sqlite3.connect(` の全 13 箇所）
書き込み＝`store.py` の `connect()`（設定済み）と `generic.py` の `promote_candidate`（設定済み）。他は：読み取り専用 URI（`legacy.py`・`revisions.py`・`generic.py`）、バックアップの書き出し先（`revisions.py`・`generic.py`・`store.py` の snapshot：トリガーは動かない）、スナップショットの検査（`__main__.py`）、別の DB ファイル（`collector.py` の collection、`monitor.py` の monitor）。この一覧は `tests/behaviour_work_stage1.py` が固定し、増減があれば試験が落ちて分類を迫る。

## 検証（すべて `SELF_VALIDATED`）
| 何を | 結果 |
|---|---|
| パッチが配布版に綺麗に当たる／逆適用できる／配布ディレクトリが 1 バイトも変わらない | 合格 |
| Work 自身の試験（`pipeline/tests`）：配布版・パッチ版 | どちらも 93 件成功 |
| 本リポジトリの DB 試験（`SOGH_PIPELINE_ROOT` でパッチ版を指す）：127 件 | 成功 |
| 最終のガード規則（能力ゲート・承認済み head・`recursive_triggers`）の下で、パッチ版：stage・finalize・2 回の更新・順の rollback・`recover_candidates`・QA 却下 | 成功（合成 DB） |
| 同じ規則の下で、配布版 | **拒否される**（依存の証明） |
| D1（candidate を head に）・D2（偽造承認）・D3（rolled_back の根拠を head に）・D4（REPLACE） | パッチ版＋規則で拒否。関数を登録しない接続は全て拒否。`recursive_triggers` が無ければ REPLACE が通る（両方が要る） |
| 改訂理由：渡せば 1 行・渡さなければ 0 行。表が無い／矛盾する理由は承認ごと戻す | 成功（合成 DB。実クローンには `revision_reasons` がまだ無い） |
| `generic.promote_candidate` が守られた DB へ併合できる（配布版は失敗） | 成功 |
| **実コピー v06 の使い捨てクローン、g4 の 22 ケース**：パッチ版・規則なし | 21 合格・0 失敗・1 既知の限界（PR #63 の監査と同じ） |
| 同：パッチ版・**ガード規則つきのクローン** | **22 合格・0 失敗**（X10：head への直接書き込みも拒否） |
| 同：配布版・ガード規則つきのクローン | 中断（`no such function: sogh_write_ok`）。記録のみ |

記録：`reports/db-audit/real_copy_g4_stage1_patch_2026-11-01.json`。再現：`SOGH_G4_PREPARE=src.integration.g4_prepare:prepare`（PR-3 以降。当時は試験用の仮のガード規則だった） を付けて `real_copy_g4_audit.py` を実行。

## 限界・次
- 検証時のガード規則は**試験用の仮の規則**だった。PR-3（`0004` の凍結再発行）が本物の移行に置き換え、同じ試験・g4 を再実行した（`docs/M1_FROZEN_MIGRATIONS_B.md`）。
- Work の呼び出し側（`scripts/revise_notices.py`）は理由を渡していない。理由の文面は Work／運用の決定で、Claude は推測で埋めない（`reason=None` なら行は作られず、監査で `missing` と見える）。
- ディスク満杯・電源断は NOT_RUN。原本・公式サイトは未接触。M1 は 2/8、**NOT ACCEPTED** のまま。
