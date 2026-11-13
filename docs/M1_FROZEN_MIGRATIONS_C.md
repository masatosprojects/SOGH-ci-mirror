# M1 凍結 SQL への再発行（その 3）：0005（G-07）・0006（G-11）（Claude の代行、2026-11-02）

**ラベル：`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用への適用）。** 旧案の PR #72（未マージ）を、統一設計の凍結 SQL として**置き換える**（#72 はマージせず、この PR のマージ後に閉じる提案）。**どの運用DB・原本・監査コピーにも適用していない。使い捨てクローンだけ。** M1 は 2/8、**NOT ACCEPTED**。

## 0005：改訂記事が引く「根拠の版」を行にする（G-07）
- `revised_article_evidence(記事, 根拠の版, case)`：主キーで重複拒否、**根拠が実在し記事と同じ case・alias でないこと**をトリガーが検査（1 件でも不正なら改訂記事の挿入ごと拒否）、**追記専用**、書き込みはゲート。行は `AFTER INSERT ON revised_articles` が record の `evidence_ids` から作る（Work の `finalize` は無変更）。
- 既存の改訂記事は、**record が述べ、DB が確認できる行だけ**を移行時に補う。確認できない参照は入れず、`v_revised_article_evidence_mismatch` が差を表示する（推測しない）。旧行は 1 行も変えない。
- `v_article_citations`（初版・改訂の引用と root）、`impacted_articles`（root からの逆引き）、**`cited_version`（記事が引いた版。head を一切見ない。引いていない版を黙って返さない）**。

## 0006：改訂の理由（G-11）
- `revision_reasons`（batch ごとに 1、追記専用、矛盾した理由と空の理由は拒否）。**訂正は上書きせず**、`revision_reason_corrections`（番号つき・追記専用・連番を強制）に追加し、`v_batch_reason_current` が最新の訂正を反映して見せる。最初の理由は残る。
- `revision_reason_contract`：移行の時点の `update_batches` の**行位置**を一度だけ記録。過去の batch に理由は作らない（`v_batch_reason_status`：`recorded`／`missing`〔契約の後で理由が無い〕／`not_recorded_before_the_contract`〔過去〕／`not_applicable`）。
- **書く側**：PR #76 のパッチで、Work の `finalize(..., reason=...)` が同じトランザクションで書く。呼び出し側（`scripts/revise_notices.py`）はまだ理由を渡さない：**理由の文面は Work／運用の決定**で、推測では埋めない（無ければ `missing` と見える）。

## 検証（`SELF_VALIDATED`）
- 合成試験：`tests/test_g07_g11_frozen.py`（25）。チェーン全体の適用・`plan` の試行（コピー上で依存順に試す）・旧行の不変・再実行の冪等・既存の同名の表で停止してファイルは不変・ゲート（素の接続は拒否）・追記専用・訂正の連番。
- **実コピー v06 の使い捨てクローン**：追加型監査 17/17（新規 C1：改訂記事 22 本、関係の行 **220**＝record から数えた期待値と一致、不一致 0、孤児 0。C2：理由 0 行〔過去に作っていない〕、状態は `not_recorded_before_the_contract` 10・`not_applicable` 19・`missing` 0、root `EV-G27-01-e1137e` の版を引く記事は 8 本）。g4（Work の更新経路＝パッチ版）**22/22**（承認した新記事の関係の行が、引用した版の数と正確に一致）。監査コピーの SHA は不変。記録：`reports/db-audit/real_copy_frozen_c_2026-11-02.json`。

## 残り・限界
- G-06（原典メタデータ・検証イベント）と索引 6 本は次の PR（PR-5）。Work の独立レビュー前。全国規模の性能・ディスク満杯・電源断は NOT_RUN。運用への適用は別の承認が要り、**PR #76 のパッチの取り込みが先**。
