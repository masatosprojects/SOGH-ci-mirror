# M1.g1／G-05：凍結移行 0011-g05-alias-provenance と 01 の来歴の4規則｜Claude の実装（2026-11-08 夜）

**ラベル：`SELF_TEST`・`INDEPENDENT_QA_PENDING`。** 受容でも適用でもない。M1 は 2/8 NOT_ACCEPTED。どの運用DBにも適用していない。
根拠：本人の決定（2026-11-08、#199 comment 6722534424）『案1＋案2を 0011 で登録』、`docs/G05_ALIAS_PROVENANCE_STORAGE_PROPOSAL_2026-11-08.md`、`G05_OWNER_REVIEW` §12〜13。作業はこの PC 上で行った（ゲーミングPCには何も運んでいない）。

## 作ったもの
| 物 | 内容 |
|---|---|
| `migrations/0011_g05_alias_provenance.sql`（凍結、SHA-256 `1cf76e79974ac05855bb4f0491e24612f478b4320aa5c9a09f96d5327e630904`） | 空の追記専用表 2 つ＋ガード 8：`alias_provenance_bundles`（別名ごとに内容アドレスの来歴の束 1 件）、`source_representations`（原典の媒体 pdf／html／unknown を版つきで）。0007 の `source_kind`（役割）は変えない。行を入れない |
| `additive_schema.py` | 0011 を連鎖に登録（`user_version` 11）、事前検査（`evidence_aliases`・`source_documents` が無ければ not_applicable、同名があれば停止）。`register_alias` の承認つき登録に `provenance_bundle`・`recorded_by` を追加（別名と束は 1 つの SAVEPOINT で、片方だけは残らない）。通常登録は束を拒否 |
| `alias_provenance.py`（新） | 束の保存・検証、媒体の記録・参照、**位置の差の判定** `explain_position_differences` |
| F-2 アーカイブの試作・`test_pr96_*` | 0011 → **0012** に番号を直した（承認どおり） |

## 位置の差の4規則（許可リストはこの4キーだけ。ほかは従来どおり拒否）
| キー（差の向き） | 外れてよい条件 |
|---|---|
| `pattern`（別名にのみ） | 保存された束が、登録しようとする**別名の記録そのもの**を残し、束が検証できる（SHA・必須キー・同じ別名） |
| `quote_normalized`（別名にのみ） | 値が、契約の正規化（`identity._squash`＝文字列全体の NFKC＋空白除去）で `quote` から**再計算した値と等しい**。違えば拒否（抽出器の文字ごとの正規化は別の関数） |
| `section`（head にのみ、明示の null） | 束が『生成プロファイルは節の制約を使っていない』と**証明**している（`section_constraint == {used:false, proven_by:<束のプロファイル SHA>}`）。証明が無い欠落は null ではない。非 null は両側が等しいこと |
| `source_kind`（head にのみ） | 原典の**記録された媒体**と等しい。記録の無い原典は unknown で、何とも一致しない（`unknown` という語とも）。PDF と HTML は別物 |
位置を表すキー（page・quote・開始終了）の差、対にならない proof、field proof の差は、**束が完璧でも拒否**。

## 検証（SELF_TEST。合成DBと、この PC 上の実コピーの複製・保存 PDF）
| 何を | 結果 |
|---|---|
| 新試験 `tests/test_m1_0011_alias_provenance.py` 29 件：凍結ファイルの固定、空の2表、同名の既存物で停止、01 型の登録（4キーすべて説明あり）、説明が欠ける10通り（束なし・別の記録の束・節の証明なし・別のプロファイル・媒体の記録なし・媒体の食い違い・quote_normalized の誤り・未知のキー・必須キー欠落・recorded_by なし）で**何も書かれない**、位置キー4通りは拒否、非 null の節、同一位置は束不要・通常登録は束を拒否、媒体の版管理、追記専用（recursive 0／1、REPLACE、負 rowid）、改ざんした束を監査が検出、DB-17・受容ゲート | 合格 |
| 変異試験：規則・原子性・追記専用の 14 個 | **全 14 個を検出** |
| 既存の試験（連鎖の長さに依存するもの）の修正 | 全体のローカルCI は下記 |
| **実コピー v06 の複製（C: 上）に 0002〜0011 を一括適用** | 10 件適用・ロールバックなし、受容ゲート・`verify_*`・来歴が空、`user_version` 11、旧表の行数は不変、`db_audit` 失敗 0・DB-09／DB-17 pass・警告2（DB-14・15、従来と同じ） |
| **g1 の PDF 本文の照合（保存 PDF そのものを開く。この PC 上、SELF_TEST）**：`e1137e2a…`（1,721,943 バイト、45 ページ、SHA 一致） | root `EV-G27-01-e1137e`・訂正の改訂 `EV-U-8d8e1d177883`・別名 `EV-G27C-01-e1137e` の**すべての引用が p.6 の本文にあり、正規化位置が本文と一致**。文脈パターンは p.6 だけに 1 件一致し、取得群 `count` ＝ **16**（値 16 と一致）。数値 16 の引用（721–723）は 16 ページに現れる短い語だが、位置と文脈パターンで p.6 に固定されている |
| **実際の別名・head の記録での判定**：`position_differences` ＝ p.6 の 2 区間で `pattern`・`quote_normalized`（別名にのみ）、`section`・`source_kind`（head にのみ）（Work の診断と同じ）。実際の記録から作った束（別名の記録そのもの、プロファイルファイル `tsukuba-klis-general-2027.json` の SHA、媒体＝保存 PDF を開いて解析）で判定 | `pattern`・`quote_normalized`・`source_kind` は説明できた。**`section` は、束に『節の制約を使っていない』という証明の主張を入れて初めて説明できる**（プロファイルファイルに `section` の語・キーは無い）。主張を入れない束では `section` だけが理由として残る |
| **実コピー v06 の複製に、01 の承認つき登録を実演**（root・head・source が複製にある） | 登録成功（別名は `EV-U-8d8e1d177883` に固定、`cited_version_fixed`＝true）、束の検証は空。**複製であり、原本・運用DBへは適用していない** |

## 01 が受容されるために、まだ要ること（本人の判断が中心）
1. **`section` の証明の扱い**：束の `section_constraint` は『生成プロファイルが節の制約を使っていない』という**主張**で、根拠は『プロファイルファイルに `section` に関する項目が無い（SHA 固定）』ことだけ。Work の条件（『生成したプロファイルまたは原典の記録で証明できる場合だけ』）に、これで足りるかは**本人（契約レビュー）の判断**。足りなければ 01 の `section` は拒否のまま。
2. **束の作成者と中身**：実際の束は、Work の抽出器の版（`extractor_version`）・正規化器の識別子を、Work の記録で確定させる必要がある（今回の値は Work の記録から私が書いたもの＝要確認）。
3. **運用DBへの適用と実際の登録**（別の承認）。
4. Work の契約合意（G-04／G-05）は、本人のレビューの記録で置き換える（本人の明示が必要）。
5. 同時更新時の互換出力（実コピーでの比較）と、独立QA。

## NOT_RUN・限界
Antigravity の独立QA（ゲーミングPCは実コピー・PDF を持たない。本人の方針でこの PC 上で行う）、運用DB・原本への適用、GitHub Actions（課金によりジョブ未開始）、Windows 以外・Python 3.11。PDF の照合は私の自己試験で、**独立の証拠ではない**。
