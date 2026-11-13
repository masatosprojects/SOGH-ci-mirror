# 修正版で再生成した FAQ 候補（提案・複製上の出力）｜Claude、2026-11-08、SELF_TEST

`faq-candidate.regenerated.json` は、**修正版（PR #276 のパッチ）の抽出を、保存済みの公式 FAQ 本文 `dad557c5…`（メインPCの保存本文を読み取りだけで複製）に実行した出力**。Work の `research/inbox/work-faq-v3/candidates/faq-candidate.json` は**変えていない**（Work の manifest のハッシュ対象）。これを Work の配布物に反映するかは本人の判断（承認前の提案）。引用文は既存の候補と同じ（新しい本文はリポジトリに載せていない）。

## 配布版の候補との差（全 23 件。これですべて）
| 内容 | 件数 | 旧 → 新 |
|---|---|---|
| `proofs[0..4].section` | 5 | 大見出し『ＡＣ入試の選考で重視されるのは…ですか？』→ 質問 1『生成AIを使用した場合は、どこまで下線を引けばよいのでしょうか？』 |
| `proofs[5].section` | 1 | 大見出し → 質問 2『生成AIで作成した画像（図や表等も含む）はどのようにすればよいでしょうか？』 |
| `base_record.proofs[0,1].section` | 2 | 大見出し → 質問 1、質問 2 |
| `field_proofs.*.applies_to` | 5 | `tsukuba-klis-ac-2027` → `null` |
| `base_record.case_id`／`faculty`／`department`／`fiscal_year` | 4 | `tsukuba-klis-ac-2027`／情報学群／知識情報・図書館学類／2027 → `null`（STR-076） |
| `base_record.scope` | 1 | `target_admission_cycle` → `general_admission_faq` |
| `base_record.scope_status`／`scope_reverification` | 2 | （無し）→ `unknown`／`required` |
| `base_record.applicability` | 1 | 『今年度実施分に基づく説明』→ 年度・学類・実施年の対象は原典から確定できない（UNKNOWN、STR-076） |
| `base_record.profile_version`／`evidence_id` | 2 | 設定の `profile_version` を `faq-conditions-2026-11-08-v2-scope-unknown` にしたため（適用範囲が違えば証拠の同一性も違う）、`EV-U-467264a91b3e` → `EV-U-d3bea8f5a272` |

**変わらないことを確認した**：5 条件の値、`unknown_conditions`、`retrieved_at`、`published_date`、条件の proof の引用文・ページ・正規化位置（7950–7994／7994–8045／8045–8097／8097–8146（2 件）／8183–8226）、`base_record` の anchor の位置（7918–8146／8146–8226）、`source_sha256`。

## 記事の『未確認』節の文言案（G2-5。本人が文言を決める。実装は決定後）
STR-076 §4：未確認を明示し、検証可能な公式の確認先を案内する。UNKNOWN の FAQ は特定年度・学類の記事の事実として載せない。
> **公式FAQの案内（適用年度・学類は未確認）**
> 大学公式サイトのFAQ（AC入試の節）には、生成AIを使った場合の下線の引き方や、画像・図・表の扱いが書かれています。ただし、このFAQの文面からは、どの年度・どの学類の出願に当てはまるかを確認できていません。出願の際は、必ず最新の募集要項と、公式サイトのFAQ（https://ac.tsukuba.ac.jp/consultation/faq/）、大学の窓口の案内で確認してください。
> （以下、`render_conditions` が確認済みの 5 条件から作る 3 文：生成AIが生成・修正した箇所への下線／校正機能・他人の助言の扱い／画像・図・表の明示）

実装上の注意：現在の `check_article_conditions` は見出し『提出書類と生成AIの条件・例外（公式FAQ）』を固定で検査し、`case_id` が一致する記録だけを記事に付ける。『未確認』節は**別の見出しと別の経路**（`case_id` を持たない記録専用）になり、通常の節と取り違えられないように検査も分ける。これは Work の記事コードへのパッチ提案になる（次の作業、承認後）。
