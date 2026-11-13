# Work の 5 PR の判断表と、ゲートごとの「残る 1 つのこと」（2026-11-02）

**ラベル：Claude の整理（`SELF_VALIDATED`）。M1 は 2/8（g4・g8）、NOT ACCEPTED。ここに書く「通った」は、ゲートの合格でも運用への適用の承認でもない。** 統合（マージ）は Work の PR について Claude は行わない。
**CI について**：GitHub Actions は無料枠の上限で起動せず、**CI の結果はない**。下の数字はすべてローカル（Windows・Python 3.12、まっさらなチェックアウト、`scripts/local_ci.py`）で、Linux・Python 3.11 は未実行。

## 1. 6 つの状態を分けた判断表
凡例：✔ 確認した／△ 一部／✘ いいえ（未達）／— 該当なし。
| PR（最新 head） | ① コードとして**レビュー可能** | ② **合成**の試験を通る | ③ **実データ**で独立に確認 | ④ **契約が合意**された | ⑤ **M1 のゲート条件**を満たす | ⑥ **運用適用が承認**された |
|---|---|---|---|---|---|---|
| **#109** 架空 read 契約（`6a9bda9`） | ✔ `PASS_WITH_WARNINGS`（P-1・P-2 修正を確認。P-3・W-3 を新規指摘） | ✔ Work 65＋Claude 364（古い head では 301 件失敗＝判別できる） | — 架空のみ（実データを使わない設計） | ✘ 受理は別（発行元・版・有効期限、質問の分類、年度の取り決めなど。`docs/reviews/PR109_*` の再レビュー節） | — 8 ゲートに無い（面接機能の境界） | ✘ |
| **#94** 原典の登録（`659e4f1`） | ✔ `PASS_WITH_WARNINGS`（R-1 修正を確認、旧 CI 失敗 4 件は #106 で解消） | ✔ Work 20＋Claude 23（偽造・未来・同一ファイル自己観察の拒否など） | △ 3 原典の SHA・引用 11/11・意味を独立確認。訂正候補 3 件も原典に根ざすことを確認（新しい検査 29 件）。**公式サイトからの live 取得は未実施** | △ 証拠の水準（`docs/SOURCE_EVIDENCE_LEVELS.md`）と訂正版の契約案（`docs/EVIDENCE_CORRECTION_VERSION_CONTRACT.md`）は提案済み、合意前 | ✘ g2 | ✘ |
| **#96** F-2 回収（`6f46a20`） | ✔ `PASS_WITH_WARNINGS`（G-1・G-5 修正を確認。G-2 は検証器で緩和） | ✔ Work 25＋Claude 34＋試作の仕様 18 | ✔ 欠落 36 行を旧コピーから独立に再計算してアーカイブと完全一致（監査コピーは不変） | △ 復元の契約案と G-2（追加移行＋DB-17）の具体案を提案済み（`docs/F2_RESTORATION_CONTRACT_PROPOSAL.md`、`docs/F2_G2_MIGRATION_AND_DB17_CONTRACT.md`）、合意前 | ✘ g3（アーカイブの保全は復元でも受容でもない） | ✘ |
| **#99** G6 合成更新（`9a5d467`） | ✔ `PASS_WITH_WARNINGS`（H-1 修正と H-2 の経路の分離を確認） | ✔ Work 16＋Claude 25 | ✘ 合成の更新だけ。実際の公式更新は未実施 | △ 重複指摘の「文脈」の契約案（`docs/QA_DUPLICATION_CONTEXT_CONTRACT.md`、報告専用・しきい値不変）を提案済み、合意前 | ✘ g6（全体 QA が不合格のまま：1＋299） | ✘ |
| **#103** G7 京都大学理学部（`a850773`） | ✔ `PASS_WITH_WARNINGS`（K-1〜K-4 修正を確認、K-5 は情報） | ✔ Work 25＋Claude 31（実 PDF 2 件を含む）＋契約候補の検査 32 | ✔ 概要表の罫線と文字から独立に 5 行・274・311・37 を導き Work と一致 | △ 実装契約の候補（`docs/G7_TABLE_CELL_CONTRACT_V1_CANDIDATE.md`）を提案済み、合意前 | ✘ g7（DB 登録→記事→QA の E2E が未実施） | ✘ |

### 読み方
- ②は「合成の入力で期待どおり」。③は「本物の資料／コピーを私が別の手段で再計算して一致」。①②③が揃っても④（契約の合意）と⑤（ゲート条件）が別に必要で、⑥はユーザーの判断。
- 「PR のコメントで PASS_WITH_WARNINGS と書いた」ことは、④の契約の受理ではない。

## 2. ゲートごとの「残る 1 つのこと」
| ゲート | 状態 | 残る 1 つ（それ以外の条件が整っている前提ではなく、**最後に必ず要るもの**） | 担当 |
|---|---|---|---|
| g1 識別 | 未 | G-04（学科が空のサイクル 1 件）の解消または受容と、G-05（同じ原典・同じ値が 2 つの case_id、5 群）の別名の採用——**ユーザーの判断**（解消の手段は DB の契約で用意済み） | ユーザー＋Work |
| g2 原典 | 未 | 3 原典の **live の Collector 取得による `official_site_authenticity=pass`**（いまは `not_run`。人の意味確認は別の項目） | Work（実行）＋Claude（独立確認） |
| g3 保全 | 未 | **F-2 の受容の署名**（旧 36 行のうち 30 行の復元の可否を含む。アーカイブは保全であって受容ではない） | ユーザー |
| g4 更新の安全性 | **達成** | — | — |
| g5 移行 | 未 | v0.2 を含む**実際の移行の実行と監査**（いまは更新であって移行の実行ではなく、v0.2 は保留） | Work＋Claude |
| g6 影響分析 | 未 | **実際の公式の新しい告知**を、実際の更新経路で記事の改訂まで通し、全体 QA が（合意したルールのもとで）通ること | Work＋Claude |
| g7 新様式 | 未 | **1 区分（数理科学入試）の DB 登録→記事→QA の E2E**（承認済みの `fact_key` が前提） | Work＋Claude |
| g8 独立監査 | **達成**（範囲：コピーまで） | — | — |

## 3. 今回追加した Claude 側の成果物（すべて報告専用・契約案・試験で、運用には触れない）
| 成果物 | 内容 |
|---|---|
| PR #109 の再レビュー | 再レビュー節、回帰試験（364）、Sandbox のガード修正（「合格率は 80%」） |
| 訂正版の契約と検査（#94） | `docs/EVIDENCE_CORRECTION_VERSION_CONTRACT.md`、`src/integration/evidence_correction_check.py`、試験 29 |
| G-2 の具体案（#96） | `docs/F2_G2_MIGRATION_AND_DB17_CONTRACT.md`、試作の仕様試験 18（リポジトリに SQL 移行は追加していない） |
| 重複の文脈の契約（#99） | `docs/QA_DUPLICATION_CONTEXT_CONTRACT.md`、`src/article_qa/duplication_context.py`、試験 23 |
| 表セル根拠の実装契約（#103） | `docs/G7_TABLE_CELL_CONTRACT_V1_CANDIDATE.md`、`src/integration/table_cell_evidence_check.py`、試験 32 |
| Sandbox の品質セット（2） | 追質問・節の分離・一貫性の試験 18、**追質問が同じ言葉を繰り返す欠陥の修正**、`docs/SANDBOX_EVALUATION_HUMAN_ONLY_ITEMS.md` |
| 課金なしの運用 | `scripts/local_ci.py`、`docs/LOCAL_CI_AND_NO_COST_OPERATION.md`（#114 で統合済み） |

## 4. ユーザー判断が必要な項目
F-2 の受容と 30 行の復元／G-04・G-05 の扱い／固定文（足場）を重複判定で区別する契約変更の可否／新しい `fact_key` の登録／Work の PR（#94・#96・#99・#103・#109）の統合／運用 DB への適用／Linux・Python 3.11 を無料で覆すための準備（WSL の Ubuntu、Python 3.11 の公式インストーラー。**どちらもダウンロードがあるので許可が要る**）。
