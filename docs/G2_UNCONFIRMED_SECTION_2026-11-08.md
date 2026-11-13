# M1.g2：記事の『未確認』FAQ節のパッチ提案（第 2 パッチ）｜Claude（2026-11-08 夜）

**ラベル：`SELF_TEST`・`WORK_REVIEW_PENDING`（本人が契約レビューを代替）・`INDEPENDENT_QA_PENDING`。** 受容でも適用でもない。Work の配布物（`research/inbox/`）は変えない。M1 は 2/8 のまま。
根拠：本人の決定（2026-11-08）『文言案のまま採用』（`patches/g2-faq/regenerated/README.md`）、STR-076 §4。

## 何を作ったか
`patches/g2-faq/work-faq-g2-unconfirmed-section.patch`（第 1 パッチ #276 の**後**に当てる。既存 1 ファイル＋新規 1 ファイル）。
- `admissions_pipeline/unconfirmed_faq.py`（新）：見出し『## 公式FAQの案内（適用年度・学類は未確認）』と、本人が採用した前置きの文言、`render_unconfirmed_section`（前置き＋`render_conditions` が確認済みの 5 条件から作る 3 文、すべてに根拠の引用 `[EV-…]`）、`check_unconfirmed_section`（節がちょうど 1 つ・統制された雛形と一致・根拠が節の外に出ない・年度や学類の語が無い）。
- `notice_articles.revise_article`：`scope_status: unknown` の FAQ 記録は、**case が一致する通常の通知とは別に**、固有の見出しの別節として、既存の FAQ 節の後・『編集上の助言』の前に出す。参考資料の行に『（適用年度・学類は未確認）』を付ける。通常の FAQ 節と取り違えない（見出し・検査・引用の置き場が別）。`evidence_ids`・`claims` に含める。記録が無い場合の出力は従来どおり。

## 検証（SELF_TEST）
- 第 1 パッチ後の複製に当たる／二重適用は拒否／逆適用できる／変更は 1 ファイルのみ＋新規 1／Work 自身の試験 93 件が成功／M1 段 1・第 1・第 2 の 3 パッチの合成でも 93 件成功／ネットワーク・DB・プロセス呼び出しなし（ラッパー試験 6 件）。
- 振る舞い試験（`tests/behaviour_g2_unconfirmed.py`、14 件）：未確認節が前置きを先に述べ全文に引用がつく／年度・学類・cycle の語が無い／通常の FAQ 節と別節で両方の検査が通る／未確認の記録が通常節に混ざらない／記録が無い記事は従来どおり／改訂の同一性が変わる／改ざん 7 通り（文の変更・見出しの重複・節外の引用・前置きの削除・年度の追記・別の根拠・見出しの欠落）を拒否／case つきの記録は未確認節に描画できない／『unknown』なのに束縛を持つ記録は描画できない。
- **NOT_RUN**：第 2 パッチ自体の変異試験、独立QA（Antigravity）、実際の記事への適用（候補データは複製上のみ）、GitHub Actions（課金によりジョブ未開始）。

## 重要な限界（**本人／Work の判断が要る**）：この節は、今の保管先には登録できない
未確認節は『記事が根拠を引用する』という既存の規則に従って根拠を引用する。ところが、**適用範囲が未確認の証拠は、今のスキーマの保管先に入らない**：
- `facts.case_id` は NOT NULL で `admission_cycles` を参照し、`admission_cycles` は `faculty`・`fiscal_year` が NOT NULL。
- `RevisionStore.stage` は case が一致しない記録を『cross-cycle』で拒否する（#276 の試験で固定）。
したがって、この節を含む改訂記事は、**組み立てて検査できるが、`finalize`／承認の経路には載らない**（引用先の根拠が登録できないため）。これは設計上の矛盾ではなく、STR-076 が意図した『特定の年度・学類へ割り当てない』の帰結。進めるには、本人の判断が要る：
| 案 | 内容 | 影響 |
|---|---|---|
| **A（私の推奨）** | **範囲未確認専用の『枠』のサイクル**（例 `case_id = unscoped:tsukuba-ac-faq`）を、年度・学類を持たない特別な行として認め、UNKNOWN の FAQ をそこに登録する。`faculty`・`fiscal_year` を NULL 可にするか、固定の『UNKNOWN』値の行にする | `admission_cycles` の制約か、特別行の取り決め（新しい凍結移行 0012 以降）。DB-02/04/10 の定義も見直し。記事が引用できるようになる |
| B | 未確認節は記事に**出さず**、別の『確認先の一覧』として記事の外に置く | スキーマ変更なし。記事の中の根拠の規則に触れない。利用者への表示は別の面 |
| C | 当面、FAQ 節を記事から外す | 何も変えない。UNKNOWN のまま保持 |
本人の以前の回答は『未確認と明示して別扱い』（＝A または B）。A か B かを選んでいない。**選ぶまで、第 2 パッチは提案のまま**。

## 次
本人が A／B を選ぶ → A なら 0012（枠のサイクル）を凍結移行として実装し、F-2 アーカイブ（Work の候補）は 0013 になる／B なら記事の外の面の設計。

## C-01 (2026-11-11): per-sentence citations and the STR-101 scope-evidence guard (SELF_TEST; independent QA = Antigravity A-04, NOT_RUN)
Two findings of the D03 comparison (PR #311, `docs/D03_FAQ_UNCONFIRMED_286_VS_306_20261110.md`) are answered inside the SAME second patch (`work-faq-g2-unconfirmed-section.patch`, regenerated; it still needs the first patch):
1. **Every derived sentence is cited.** An element of `render_conditions` may hold two sentences; the citation used to follow the element only. `render_unconfirmed_section` now splits an element at `。` and cites each sentence (the notice keeps the owner's adopted wording, cited once at its end).
2. **STR-101 (H3=B): binding needs an independent official evidence.** `extract_conditions(record, spec, cycle, scope_lookup=None)` no longer binds a FAQ page to ONE cycle because a CONFIGURATION names it (the D03 probe `q1_04`: dropping `scope_status` from a spec rebound the page to the 2027 cycle). The bound path now needs `spec["scope_evidence"]` (new module `scope_evidence.py`): an evidence id and the SHA-256 of a source that is NOT the FAQ page, the cycle's case id and year, the faculty, and a quote that states the year and the faculty; it must be consistent with the cycle. With a `scope_lookup` (the evidence store) the evidence id must be registered there with the same source SHA and a text that holds the quote. A missing, self-referencing, inconsistent or unsupported evidence is an error and the record stays UNKNOWN. No path makes a record "verified" (STR-102).
   Work's own fixture (`tests/test_faq_policy.py`) now carries a controlled independent evidence; **Work's 93 tests still pass** with the stage-1 patch and both g2 patches. Work's real configuration `config/faq-structured-v3.json` has no such evidence: a run that binds the real FAQ page to the 2027 cycle now stops (fail closed) until an independent official evidence (e.g. the registered 2027 requirements) is declared.
- Tests: `tests/behaviour_g2_scope_evidence.py` (new, 13), `tests/behaviour_g2_unconfirmed.py` (per-sentence), `tests/test_g2_unconfirmed_patch.py` (the patch now changes three files and adds two).
- D03 probes on this build (`tests/qa_d03_pr286_probes.py`): 22 PASS / 2 FAIL (was 21 / 3). `q4_12` (per-sentence) now passes; `q1_04` now FAILS BY REFUSAL (`ValueError: ... not proven (STR-101)`), which is the safe behaviour the probe was asking for (it asserted `case_id is None`); `q5_15` (the unconfirmed evidence cannot be registered in the pipeline's store) remains: the storage table now exists in the contract schema (migration 0012, PR #342) but Work's pipeline store is not wired to it (that wiring is a separate step).
