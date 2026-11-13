# M1 移行・実装計画（依存順序・旧DB保全・試験・復元・Work レビュー）

`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_DECISION_REQUIRED`。正本は `M1_UNIFIED_DATA_ARCHITECTURE_RFC.md`、判断は `M1_DESIGN_DECISION_MATRIX.md`。**この計画は実装の許可ではない。運用DB・原本・監査コピーへの適用は、ユーザーの承認と Work の独立レビューの後。**

## 0. 前提
- 0002〜0006（G-04・G-05・G-09・G-07・G-11）は**どの運用DBにも未適用**。使い捨てクローンの履歴は捨てられる。
- したがって**是正の migration を積まず、適用前に統一して再発行**する（M-07）。最初の運用DBへの適用で定義を**凍結**する。
- 旧行は一切更新・削除しない（追加のみ）。旧 v0.2 の全面移行は保留のまま。F-2 は復元も受容もしない。

## 1. 依存順序
| 段 | 内容 | 担当 | 前提 | 状態 |
|---|---|---|---|---|
| 0 | ユーザーが `M1_FINAL_APPROVAL_ITEMS.md` を承認／修正 | ユーザー | — | 待ち |
| 1 | **Work のコードの小変更**：①`finalize` が batch を approved にしてから head を動かす（同一トランザクション）、②全接続で `PRAGMA recursive_triggers=ON` と能力関数 `sogh_write_ok` を登録、③`finalize`／更新経路が `record_reason` を呼ぶ、④`generic.py`・`legacy.py`・`dimensions.py`・`store.py` の全書き込み経路で②を適用 | Work（不在中は変更しない。ユーザーが Claude の代行を許可した場合のみ、隔離ブランチで） | 0 | 未着手。**段 2 より前に必須**（先に段 2 を適用すると Work の更新経路が壊れる） |
| 2 | **凍結 SQL ファイル化**と移行の再発行（0002〜0008 の統一）：①識別（G-04：offering から原典を外し `offering_sources`）、②alias（G-05：固定版の判定を view に、alias 表）、③追記専用・能力ゲート・head は approved のみ（G-09）、④`revised_article_evidence`（G-07）、⑤`revision_reasons`＋訂正の追記表（G-11）、⑥`source_document_metadata`＋`source_verification_events`（G-06）、⑦索引 6 本（G-03） | Claude（`SELF_VALIDATED`） | 1 | 設計済み、未実装 |
| 3 | **検証の仕組み**：`plan`・`db_audit` に、定義の SHA・実行 SQL の SHA・スキーマ状態・`user_version`・順序・孤児の根拠・全 head の承認済み batch・全 approved batch の理由を追加（DB-16 以降）。`root_of`・`read_version`・`cited_version` の実装 | Claude | 2 | 未着手 |
| 4 | **使い捨てコピーでの統合検証**（§2） | Claude | 2・3 | 未着手 |
| 5 | Work の独立レビュー（Claude の全実装・設計判断） | Work（復帰後） | 4 | 待ち |
| 6 | 運用DBへの適用手順の承認 | ユーザー＋Work | 5 | 待ち |
| 7 | 運用DBへの適用：バックアップ → 使い捨てコピーで dry-run → 原子的な適用 → `db_audit` → g4 harness → 新旧の全行の比較 | Work | 6 | 禁止中 |
| 8 | `head_history`・`read_as_of`、原典メタデータの登録（3 件）、G-06 の検証イベント | Claude／Work | 7 | 未着手 |

## 実施状況（2026-11-02 追記。設計と承認は不変）
段 1（Work のコードのパッチ案）＝PR #76、段 2（0002〜0008 の凍結 SQL）＝PR #78・#81・#84・本チェーンの最後の PR、段 3（検証の仕組み：定義の SHA・適用 SQL の SHA・スキーマ状態・DB-16・DB-17）＝PR #78、段 4（使い捨てコピーでの統合検証：g4 22/22・追加型 19/19）を `SELF_VALIDATED` で実施。**段 5（Work の独立レビュー）・段 6（運用適用手順の承認）・段 7（運用DBへの適用）は未実施・禁止のまま**。段 1 のパッチの取り込みが、段 7 より先（配布版のコードは最終のガードの下で動かないことを試験で確認）。詳細：`docs/M1_STAGE1_WORK_PATCH.md`、`docs/M1_FROZEN_MIGRATIONS_{A,B,C,D}.md`、台帳 T-07〜T-11。

## 2. 使い捨てコピーでの統合検証（段 4）
1. 監査コピー v06 の SHA を確認、その複製（クローン）を作る（監査コピーは書き換えない）。2. 移行前の全表・全行・head・スキーマを記録。3. 再発行した移行を依存順に適用。4. `integrity_check`・`foreign_key_check`・DB-01〜16。5. 全旧行の同一性（DB-09）。6. Work の更新経路：g4 harness 22 ケース＋新しいケース（未承認 head の拒否、能力関数なしの接続の拒否、REPLACE の拒否、トリガー削除の検出、checksum・user_version・順序の不一致、100 世代の固定、孤児の検出、改訂資料の offering）。7. 同じ移行の 2 回目（変更なし）。8. 衝突時の全体 rollback。9. バックアップからの復元（行・トリガー・`user_version` の一致）。10. 一気通貫（RFC §13）：合成の更新で、影響する記事だけが改訂され、旧記事・旧根拠・引用版が不変。11. 初期コピーと監査コピーの SHA の不変。**区分**：`synthetic`／`repository_sample`／`copied_real_db_disposable_clone`／`not_run`。Claude が実装し検証したものは `SELF_VALIDATED`。

## 3. 復元・巻き戻し
- 適用前のバックアップ（オンラインバックアップ＋SHA＋行ハッシュ）から復元できること（試験済み）。
- 移行は 1 トランザクション（DDL を含む）で、途中失敗は全体が戻る。`user_version` と履歴も同じトランザクション。
- 適用後の修正は**新しい移行**で行い、適用済みの移行は編集しない（編集は定義の checksum が検出）。

## 4. Work の復帰後の順序
①`TEMPORARY_WORK_LEDGER.md` を読む。②Claude の自己実装（G-02・04・05・07・09・11）と本設計の判断の独立レビュー。③段 1 の変更（Work のコード）。④段 7 の適用（承認後）。Work のレビューは**ユーザーの設計承認と別**に管理する。

## 5. 試験が NOT_RUN／未検証のもの
ディスク満杯・電源断・OS の異常、全国規模の性能、`writable_schema`・ファイルの差し替え（検出と運用）、実際の公式更新の E2E（合成のみ）、署名（G-08）、`read_as_of` の実装。
