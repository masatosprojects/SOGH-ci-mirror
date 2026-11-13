# M1.g2：FAQ 抽出の修正案（見出しの引き継ぎ・STR-076）｜Claude の提案（2026-11-08）

**ラベル：`SELF_TEST`（作成者自身の試験）・`WORK_REVIEW_PENDING`・`INDEPENDENT_QA_REQUESTED`（Antigravity）。** 受容でも適用でもない。M1 は 2/8（g4・g8のみ）NOT_ACCEPTED のまま。
根拠：ユーザーの 2026-11-08 の承認（「g2 の FAQ 抽出の修正を Claude の担当として進めてよい。Work の枝は直接変更せず、新しい Draft PR での提案にとどめる」）と、Antigravity の独立QA（PR #272、Issue #199 の comment 6720856497）。STR-076 は「事業原則のみ」の承認で、実装・DB更新・M1受容の許可を含まない。

## 1. 直すもの（Antigravity が見つけた 2 件）
| # | 症状 | 原因（Work の配布版） |
|---|---|---|
| 1 | FAQ 候補の証拠 proof 0〜5（と `base_record.proofs` の 2 件）の `section` が、すべて大見出し「ＡＣ入試の選考で重視されるのはどのようなことですか？」になる。実際の直前の質問は「生成AIを使用した場合は…でしょうか？」（proof 0〜4）と「生成AIで作成した画像（図や表等も含む）は…でしょうか？」（proof 5） | `faq_policy.py` の proof 組み立てが `'section': spec['section_start']` を全 proof に固定で入れる。`supplements.py` の `extract_notice` も同じく `spec.get("section_start")` を入れる。`section_start` は節の境界を探す目印であって、各 proof の見出しではない |
| 2 | FAQ の記録が `case_id: tsukuba-klis-ac-2027`・`faculty: 情報学群`・`fiscal_year: 2027` を持つ。FAQ のページはこれらを述べていない（STR-076 違反 4 件） | `extract_notice` が呼び出し側の `cycle` の値をそのまま記録に写す。`extract_conditions` と `validate_condition_bindings` が 2027 の KLIS に固定で結びつける。設定 `faq-structured-v3.json` が `case_id`・`fiscal_year` を持つ |

## 2. 修正案（`patches/g2-faq/work-faq-g2.patch`、Work のファイルは直接変更しない）
Work の配布ディレクトリ（`research/inbox/work-faq-v3/`、manifest の SHA 検証対象）は 1 バイトも変えない。`patches/m1-stage1/` と同じく、**配布版の複製にだけ** `git apply` で当てて検証する。

| ファイル | 変更 |
|---|---|
| `admissions_pipeline/headings.py`（新規） | `immediate_heading(...)`：その proof の範囲を持つ**宣言済みの質問**（原文のまま）を返す。推測しない。質問が無い／重複／proof が質問の途中で始まる／2 つの質問をまたぐ／間に宣言されていない質問（`?`）がある、のいずれでも `ValueError`（失敗側に倒す） |
| `admissions_pipeline/faq_policy.py` | proof の `section` を `immediate_heading` から取る（`section_headings` がある仕様）。`scope_status: "unknown"` の仕様では、`cycle` を渡すこと・`case_id`/`fiscal_year` を持つこと・質問の宣言が無いことを拒否。`applies_to` は `None`。`validate_condition_bindings` は UNKNOWN の記録が `case_id`／`fiscal_year`／`faculty`／`department` を持つ・`scope` が `general_admission_faq` でないことを拒否。`audit_condition_source`（原本との機械的な照合）に「各 proof の `section` がその引用の直前の質問である」検査を追加（引き継ぎや入れ替えを検出） |
| `admissions_pipeline/supplements.py` | 同じ UNKNOWN の分岐（1 つ下の層でも同じ規則を拒否＝二重の防御）。UNKNOWN の記録は `case_id`・`faculty`・`department`・`fiscal_year` を `None`、`scope: general_admission_faq`、`scope_status: unknown`、`scope_reverification: required`。anchor の proof の `section` も直前の質問 |
| `scripts/revise_notices.py`（駆動スクリプト） | UNKNOWN の候補は `scope-unknown-held.json` に**保留**し、`stage`・記事への付与に進めない。レポートに `scope_unknown_held` を追加 |
| `config/faq-structured-v3.json` | `case_id`・`fiscal_year` を外し `scope_status: "unknown"`、`section_headings`（2 つの質問）、`university`・`admission_method`、`profile_version` を新しい値（証拠の同一性が変わるため）、`parent_evidence_id` を `null`、`applicability` を UNKNOWN の文面に |

**変えないもの**：正規化した位置（`normalized_start/end`）、引用文、`source_sha256`（dad557c5…）、5 条件の値と極性、`FIELDS` の表、SHA 固定の抽出の規則。`section_headings` のない従来の仕様は従来どおり動く（Work 自身の 93 件の試験が配布版・修正版で同じに通る）。

## 3. 検証（すべて SELF_TEST。合成のページと保存済みの候補 JSON のみ）
| 何を | 結果 |
|---|---|
| パッチが配布版の複製に綺麗に当たる／二重適用は拒否／逆適用できる／変更されるファイルが宣言の 4 つ＋新規 1 つだけ／配布ディレクトリは不変 | 合格 |
| Work 自身の試験（93 件）：配布版・修正版・**M1 段 1 のパッチと両方当てた複製** | いずれも 93 件成功 |
| `tests/behaviour_g2_faq.py`（27 件）：修正版 | 27 件成功。配布版では `headings` が無く実行できない（依存の証明） |
| 内容：各 proof が直前の質問を指す（5 条件の proof＝質問 1 が 5 件・質問 2 が 1 件、anchor＝質問 1・質問 2）。**引用文と正規化位置は配布版の抽出と一致**。UNKNOWN の記録は `case_id`／`faculty`／`department`／`fiscal_year`／`published_date` が `None`。結びつけの拒否 5 通り、記録側の拒否（4 属性＋ `scope`）、見出し保護の失敗側（質問が無い・重複・宣言されていない質問・2 つの質問をまたぐ・見出しの途中）、独立の原本監査が「引き継ぎ・入れ替え・存在しない質問・空・後ろの質問」の `section` を拒否、**配布版の引き継ぎも監査が検出**、UNKNOWN の記録は記事に付かない（`no applicable notices`）・`stage` で拒否（`cross-cycle`）・駆動スクリプトは保留して何も stage しない | 合格 |
| 変異試験（使い捨ての複製への 29 個の変異。うち設定への変異 3） | 28 個が試験で検出。**1 個は意図した冗長**（`faq_policy` だけの `cycle` 拒否を外しても、1 つ下の `supplements` が拒否する。両層を同時に外すと検出される） |
| 保存済みの候補 JSON（`faq-candidate.json`）：欠陥の存在（`section` 全件が大見出し、`case_id`＝2027・`faculty`＝情報学群）、宣言した 2 つの質問が anchor の引用の最初の質問と**文字まで一致**、5 条件の proof 6 件は保存済みの anchor 2 件のどちらか**ちょうど 1 つ**の範囲に入る＝正しい `section` が保存済みの位置だけで決まる。anchor の位置は (7918–8146)・(8146–8226) のまま | 合格 |

実行：`python -m pytest tests/test_g2_faq_patch.py -q`（約 25 秒）。

### 3b. 保存済みの**実HTML**での実行（2026-11-08 夜、メインPC。SELF_TEST）
保存済みの本文 `dad557c5…`（258,425 バイト、SHA 一致、`SOGH\outputs\faq-v3\collection\bodies\` ほか 4 か所に同一の写しがある）を**読み取りだけ**で C: に複製し（原本は SHA・サイズ・更新時刻とも不変）、配布版と修正版の抽出を同じ本文に対して実行した。
| 何を | 結果 |
|---|---|
| 配布版の実行が、保存済みの候補（`faq-candidate.json`）を再現するか | **再現した**（6 件の proof と anchor 2 件の正規化位置・引用文が一致）。`section` は全件が大見出し |
| 修正版の `section` | proof 6 件＝質問 1 が 5 件・質問 2 が 1 件（宣言した原文のまま）、anchor 2 件＝質問 1・質問 2。大見出しは 0 件 |
| 正規化位置・引用文・5 条件の値 | 配布版と**完全に一致**（6 件：7950–7994／7994–8045／8045–8097／8097–8146（2 回）／8183–8226、anchor：7918–8146／8146–8226） |
| 原本との機械的な照合 `audit_condition_source`（`section` 検査つき） | pass（条件 5、proof 参照 6、固有の範囲 5） |
| STR-076 | 記録の `case_id`・`faculty`・`department`・`fiscal_year`・`published_date` が `None`、`scope`＝`general_admission_faq`、`applies_to` は全件 `None` |
これで、Antigravity の独立QAが『保存原本未配置のため NOT_RUN』とした項目（実HTMLでの実行）を、私の側（SELF_TEST）では実行済み。**独立QAとしては未実施**（Antigravity は保存原本が手元に無い。メインPCの複製をゲーミングPCに送るかは本人の判断で、私は送らない）。

**Antigravity の独立QA（2026-11-08 夜、PR #272、#199 の comment 6721352338／6721471714）**：パッチの適用・逆適用、直近設問の解決と引き継ぎ欠陥の拒否、STR-076 の 4 属性の拒否＝いずれも合成環境で PASS（4 PASS）、実HTMLのみ NOT_RUN（SOURCE_ACCESS_BLOCKED）。新しい head `98bb4e6`（文書のみの変更）でも同じ結果。私は追試していない。

### 3c. 実HTMLでの独立QAの手順（本人が受渡しを許可。2026-11-08 夜）
`patches/g2-faq/check_real_html.py --html <保存済みの本文>` が、§3b と同じ確認（11 項目）を 1 回で行う（配布版の複製と修正版の複製を作り、配布版が保存済みの候補を再現すること、`section`・位置・引用・値・audit・STR-076 の 5 属性、本文が実行の前後で不変であること）。本文はリポジトリに置かない方針のため、**メインPC上の受渡し用フォルダ**（`C:\Users\USER\sogh-handover\g2-faq-saved-html\`、本文の写し＋`MANIFEST.txt`、SHA 一致を確認済み）に用意した。ゲーミングPCへ運ぶのは本人（私はネットワーク越しに送らない）。私の側の実行結果：11 項目すべて true、終了コード 0。

## 4. この修正で挙動が変わること（本人／Work の判断が要る）

**ユーザーの回答（2026-11-08 夜、『すべて承認します』＋範囲の確認）**：1 の記事の FAQ 節は『**「未確認」と明示して別扱い**』で承認。2〜5 は私の既定（`university`・`admission_method` を保持、`parent_evidence_id` は `null`、従来の分岐は残す、候補データの再生成は保存済み本文での実行が前提）のまま進める承認として読む（個別の回答はない）。**承認はこの PR のマージ・適用を含まない。** 記事に『未確認』の節を実装するのは次の作業（別の提案として、同じ方式で出す）。以下は承認前に書いた判断事項で、1 以外は『既定を採った』状態。
UNKNOWN にすると、FAQ の記録は特定の入試サイクルに結びつかない。これは STR-076 の意図（未確認の属性を 2027 年度の特定学類へ推測適用しない）の帰結だが、次の判断が残る。**Claude は決めていない。**
1. **記事の FAQ 節**：`revise_article` は `case_id` が一致する記録だけを付けるので、UNKNOWN の FAQ は 2027 KLIS の記事に付かない（付けようとすると拒否される）。現在の候補記事（`candidates/overview.md`・`interview.md`）にある「提出書類と生成AIの条件・例外（公式FAQ）」節は、この修正では再生成されない。外すか、STR-076 §4 に沿って『未確認』を明示して別扱いで載せるかは、Work／本人の判断。
2. **`university`・`admission_method`**：FAQ のページ（ac.tsukuba.ac.jp）と節の見出し（ＡＣ入試）から根拠づけられるとして保持した。これも UNKNOWN に落とすかは判断事項（設定の 2 キーを消すだけ）。
3. **`parent_evidence_id`**：2027 KLIS の募集要項の証拠への紐づけを外した（紐づけ自体が事実上の結びつけになるため）。残すかは判断事項。
4. **従来の分岐**：`case_id` を持つ仕様（Work の試験の固定データ）は従来どおり通る。つまり設定を書き換えれば再び結びつけられる。実際の設定でそれを防ぐには、結びつけに独立の公式根拠（STR-076 の再検証）を要求する規則が要るが、**未決**。
5. **候補データの再生成**：`candidates/*.json` と Work の manifest は変えていない。正しい `section` を持つ候補にするには、保存済みの本文（dad557c5…）に対して修正版を実行して再生成する必要がある（Work または Antigravity、読み取り専用の参照のみ）。

## 5. 独立QA（Antigravity）への依頼
- 保存済みの本文（dad557c5…）に対して修正版の抽出を**実際に**実行し、6＋2 件の `section` が期待どおり（質問 1＝5＋1、質問 2＝1＋1）で、正規化位置・引用・SHA が変わらないこと。
- STR-076：記録の `case_id`・`faculty`・`department`・`fiscal_year`・`published_date` が `None`、`scope` が `general_admission_faq`。Antigravity が用意した g2 の試験（`test_independent_qa_g2_faq_heading_extraction.py`）は、記録の `case_id` が `2027`/`klis` を含まないことを求めている点と整合する（この修正は `None`）。ただし同試験の合成記録が使う `tsukuba-ac-general-faq` は採用していない（根拠のない新しい識別子を作らない）。
- 破ってみる：宣言の質問を 1 つ消す・同じ質問を二重に宣言する・質問の間に `？` を足す・anchor を 2 つの質問にまたがせる・`section` を入れ替える、で拒否されること。
- 私の変異試験・試験自体の弱点（例：合成のページの構造が実ページと違う可能性）。

## 6. NOT_RUN／限界
- **実HTMLでの実行は SELF_TEST としては済み（§3b）。独立QAとしては未実施**（Antigravity の手元に保存原本が無い）。
- Work の駆動スクリプト全体の通し実行（監視 DB・実コピー）。UNKNOWN の分岐を合成のモニター表で確認したのみ。
- Windows 以外、Python 3.11。GitHub Actions（課金によりジョブ未開始）。実コピー・実DB・実モデル・課金・署名には触れていない。マージなし。
