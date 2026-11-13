# 回帰テストの運用（Work から新しい大学のデータを受け取るとき）

Issue: #18　実装: [src/regression/](../src/regression/)　テスト: [tests/test_regression_handoffs.py](../tests/test_regression_handoffs.py)、[tests/test_regression_harness.py](../tests/test_regression_harness.py)
報告の例: [reports/regression/](../reports/regression/)

## 何を守るか

Work が新しい大学・入試方式のデータを渡すたびに、次の3つが崩れないことを確認する。

1. **新しいデータ自体が正しく検査を通る**（取り込みゲート、fact_key 登録簿、記事QA、変異テスト、版管理）。
2. **過去のデータの結果が変わらない**（新しい草案や新しい `fact_key` が、既存の記事の検証結果に悪影響を与えない）。
3. **何が検査されて何が検査されていないかが数字で分かる**（テスト件数・成功・失敗・**skip**）。

## 仕組み（Work のファイルを変更せず、ファイル名で自動検出）

`research/inbox/**/claude-compatible-export.json` を、すべての受け渡しについて自動で見つける。
**大学名はコードに書かれていない。新しい大学は、新しい export が入るだけで検査対象になる。**

| 検査 | 内容 | 失敗したら |
|---|---|---|
| ゲート | 取り込みゲート（スキーマ＋ fact_key 登録簿） | 下記「失敗の読み方」 |
| 登録簿 | 未登録の fact_key・型違反はエラー、新しい値の項目などは警告 | 〃 |
| 記事QA | 全草案が厳密検証を通る | 〃 |
| 変異テスト | 記事の数字を1つずつ書き換える。本文の数値 ≥95%、引用ID ≥90%、**作業基準日 100%**、**引用の総当たり差し替え ≥98%** の検出が必要 | 〃 |
| 版管理 | 引用文の数字を変えると、**その事実と、それを引用する記事だけ**が影響ありになる（全事実で確認） | 〃 |
| 受け渡しをまたぐ検査 | 事実ID・記事IDの衝突なし。**他の受け渡しを混ぜても、各記事の結果は不変** | 〃 |
| ベースライン | 過去の export の結果が、コミット済みの正解（`tests/golden/qa_baseline.json`）と同じ | 〃 |
| 独立監査 | `audit_handoff`：manifest のハッシュ、個人情報・秘密情報の走査、値と引用文の整合 | 〃 |
| skip 禁止 | テストに `skip` / `xfail` の仕組みが無い（必要なデータが無ければ**失敗**する） | skip を使わない |

## 受け渡しを受け取ったときの手順

1. Work の PR の変更が `research/inbox/<受け渡し>/` に収まっていることを確認する（Claude 側の `src/`・`tests/`・`reports/` を変更していないこと）。
2. PR を手元に取得し、**一つのコマンド**で全体を検査する：
   ```
   python -m src.regression.report --run-tests --fail-on-skip --out-dir reports/regression/<日付>-<受け渡し名>
   ```
   テスト件数（合計・成功・失敗・エラー・**skip**）、受け渡しごとの検査、ベースライン、独立監査が `report.md` に出る。CI でも同じものが
   **Actions の Summary** と成果物（`regression-report`）に出る。
3. **公式PDFが手元にあるときは**、PDFとの照合も実行して結果を保存する（PDFは GitHub に無い）：
   ```
   python -m src.integration.audit_handoff research/inbox/<受け渡し> --pdf-dir <PDF置き場>
   ```
   PDFが無い／一部しか無い場合、その分は **skipped（検査できていない）と出る**。成功とは書かない。
4. 結果が「成功」で、新しい export が「ベースライン未登録」と出ていれば、**内容を確認したうえで**ベースラインに追加する：
   ```
   python -m src.regression.report --update-baseline
   git diff tests/golden/qa_baseline.json     # 追加だけであること（既存の export の行が変わっていないこと）を確認
   ```
5. PR を作り、CI の成功・競合なし・監査上の問題なしを確認してマージする。

## 失敗の読み方

| 出力 | 意味 | 対処 |
|---|---|---|
| `registry: unregistered fact_key(s) [...]` | 登録簿に無いキー | `docs/FACT_KEYS.md` の手順（#19 / #22 で提案 → `proposed` として登録）。**Work に変更を求める前に、既存の使い方に登録簿を合わせられないか確認する** |
| `gate: N invalid record(s)` | スキーマ違反または登録簿の型違反 | `fact_registry check <export>` で詳細 |
| `article ...: [findings]` | 草案が根拠と矛盾（数値・日付・年度・適用範囲） | Work に草案の修正を依頼（Issue）。QAの誤検出なら Claude 側を直す |
| `mutation: body numbers detected a/b < 95%` | 検出できない種類の記述が増えた | 見逃しの文脈を確認（`mutation_sweep`）。新しい表記なら #13 に追加、検出ルールを足す |
| `versioning: ...` | 引用文の数字を変えても影響が正しく出ない | 引用文が文字として再現できるか確認（空の引用、重複する引用） |
| `evidence id(s) already used by another export` | 事実IDが他の受け渡しと衝突 | Work に ID の付け方の修正を依頼（一意であること） |
| `an article's result changes when other exports' evidence is present` | 記事の結果が、他の受け渡しの有無で変わる | 記事が他の受け渡しの根拠IDを引用していないか確認（Work に修正を依頼） |
| `baseline: ...: baseline X -> now Y` | **過去の export の結果が変わった** | 原因を特定する（Claude のQA変更か、Work が過去の export を書き換えたか）。意図した変更でなければ戻す。意図した変更なら PR に理由を書き、ベースラインを更新（レビューを受ける） |
| `baseline lists ... but it is no longer delivered` | 過去の export が消えた | Work の PR を確認（削除は事前合意が必要） |
| `N skipped test(s)` | skip がある | テストがデータ不足で飛ばされている。**成功に数えない**。skip の仕組みを外し、データが無いなら失敗させる |

## 新しい草案が既存記事に悪影響を与えていないかの確認

- **記事QAは記事ごとに独立**で、ある記事の結果は他の記事に依存しない。受け渡しをまたぐ検査は、これを実際に確認する
  （全受け渡しの根拠を混ぜて評価し直しても、各記事の `ok`・指摘・注意が同じ）。
- 草案どうしの**近い重複・テンプレート由来の同一文**は、警告として報告する（失敗にはしない）。
  例：新潟の法学部と人文学部の「資料」記事は 87% 類似。SEO上の重複の懸念があるので、Work に内容の差別化を相談する材料にする。

## 追加された fact_key の検証ルールの確認

1. `python -m src.verify.fact_registry check <export.json>`：未登録・型違反（エラー）、未登録の項目（警告）を確認。
2. 登録簿で、そのキーの値の項目に **`kind`**（人数・分・字・…）が付いていること。付いていないと数値の照合が名前ベースの推定になる。
3. 変異テストと版管理テストが、新しいキーの事実でも通ること（本回帰テストが自動で確認する）。
4. 新しい**ルール**（言い回しの制約）が要るなら、`src/verify/data/fact_keys.json` に手がかり表現を足し、負例テストを1つ追加する。

## 件数・skip・失敗の報告

- `report.md` / `report.json`：テスト件数（合計・成功・失敗・エラー・**skip**）と skip したテストの名前・理由、受け渡しごとの検査結果。
- **skip は成功に数えない。** CI は `--fail-on-skip` で、skip が1件でもあれば失敗にする。
- 受け渡しを受領してマージするたびに、同じ報告を `reports/regression/<日付>-<名前>/` に保存する（Claude の担当）。

## GitHub Actions（`.github/workflows/tests.yml`）

| ジョブ | 内容 |
|---|---|
| `pytest`（必須チェックの名前） | Linux・Python 3.12。全テスト（`-rs`、junit 出力）→ 回帰報告（skip が1件でも失敗）→ 報告を成果物に保存、Summary に表示 |
| `pytest-py311` | Python 3.11（対応する最低版） |
| `pytest-windows` | Windows。日本語環境・CRLF など、データが作られる環境に依存した不具合を検出 |
| 週次の定期実行 | コミットが無くても、依存パッケージの更新による不具合を検出 |

## 全体ビュー（Issue #36）

`samples/current/active-state.json` のような**全体ビュー**（全大学・全方式の現在の状態）は、旧納品の根拠IDを意図的に繰り返すので、
`claude-compatible-export.json` の自動探索（隔離検査）には入れない。代わりに `python -m src.regression.fullview`（CIで毎回実行）が、
ファイル名（`*active-state*.json` / `*full-view*.json`）で自動検出して検査する。無ければ「見つからない」と出して成功（`--require-view` で失敗にできる）。

- **根拠IDの再利用と衝突を区別**：同じID・同じ事実/対象/年度/方式/原典URL/原典ハッシュ/引用位置/値＝再利用（正当）。どれか1つでも違えば衝突（失敗）。取得日時だけの違いは衝突にせず一覧に出す。
- **記事**：同じ記事IDで本文が違えば失敗（変更は新しい `:revision:` ID で行う）。改訂は、IDの末尾が `revision_hash` と一致、`base_article_id` がIDの基と一致、`as_of` あり、基の記事が存在して**本文が違う**、本文の引用が `evidence_ids` に列挙され全体ビューに存在、のとき正当な更新。基の記事がどの納品にも無い場合は「基との差分は未確認」と警告。
- 全体ビューに `evaluate_export` と同じ検査（全記事のQA・登録簿・本文/引用ID/基準日の変異・引用の差し替え・意味の反転・表記ゆれ・版管理）をかける。
- 件数：検査は **成功／失敗／not_run** を分け、意味の未検証件数を別に出す。
- **`scope=export`（CI）では原典（PDF/HTML原本）との照合は `not_run`**（リポジトリに原本が無い）。成功に数えない。原本を使うローカルの `scope=full` は Work の実行。
- `publication_approved` は常に false。**CIの成功は記事公開の承認ではない。**
- レポートは `regression-report/fullview.json`・`fullview.md` として Actions の成果物と Summary に保存。失敗すると必須ジョブ `pytest` が失敗する。
- Work の `verify_full_view.py`（PR #33）は、チェックアウトにある場合だけ、Issue #36 で提案された呼び出しで実行する（Work の報告であり証拠ではない。独立の検査は上の `fullview`）。

### 全体ビューの納品を `audit_handoff` でも監査する（Issue #48）

差分export（`claude-compatible-export.json`）が無く、manifest と全体ビュー（`active-state.json` / `full-view.json`）だけの納品は、
`audit_handoff` が `export=skipped` にせず全体ビューとして監査する（結果は `export` に入り、`whole_views` に詳細が出る）。
- 形状（evidence はIDをキーとする空でないオブジェクト、記事は article_id・text・claim を持つ）、Phase E ゲートと記事QA、`values_in_quotes`、
  旧納品とのID再利用／衝突（同じIDで値・年度・方式・原典・引用位置が違えば失敗）、記事の改訂履歴、manifest（一覧・SHA-256・一覧にないファイル）。
- 正式名（`active-state.json` / `full-view.json`）のファイルは壊れていても必ず全体ビューとして扱い、**失敗にする**（黙って無視しない）。それ以外の名前（Work の `qa/full-view-final.json` のような報告）は、`evidence` と `articles` を持つときだけ全体ビュー。
- 原典（PDF/HTML原本）が無い項目は `skipped` / `not_run` のまま。**`skipped` を `passed` にはしない**。差分exportの判定は従来のまま。
- CI の `src.regression.fullview` も、正式名の全体ビューが壊れていれば失敗にする。

### 意味の反転の閾値と「未検証として報告」

意味の反転のゲートは、**黙って見逃した数**（検出もされず、その文が `semantic_coverage` の未検証にも載っていない反転）で判定する（≥95%）。
生の検出率と「検出できず未検証として報告」の件数は、必ず並べて出す。根拠に比較できる構造化された値が無い文（例：『下線不要です』）は検出できないが、
未検証として人に知らせている。Work の全体ビューは 検出 78/83（94.0%）、未検証として報告 4、黙った見逃し 1（言語の列挙）。既存10草案の検出率は変わらない。

## 閾値と、その根拠

`Thresholds`（`src/regression/checks.py`）：引用の総当たり差し替え ≥98%（実測 99.4%〜100%）、本文の数値の検出 ≥95%、引用IDの検出 ≥90%。
実データの現状は、本文 98.6%〜100%、引用ID 94.7%〜98.8%。**閾値は実測より低く置き、実測の正確な値はベースラインで固定**している
（閾値は「大きく劣化していないか」、ベースラインは「少しでも変わっていないか」を見る）。
表記ゆれ（Issue #13）：実草案の完全な日付を10種の書き方に書き換え、**すべて通る（誤検出0）**ことを求め、同じ書き方で1日ずらした日付の検出 ≥98% を求める
（`notation_detection_min`、実測 100%）。報告に両方の分子/分母が出る。
意味の反転（Issue #9）：既知の反転（`flip_sweep.FLIPS`、25種）を実草案に1件ずつ入れ、検出 ≥95%（`flip_detection_min`、実測 98.6%）を求める。
**保留 C（規則を書くときに見ていない言い回し）は警告として報告のみ**（実測 56.8%）。閾値にすると規則を C に合わせて調整してしまい、汎化の測定でなくなるため。
報告には「意味の未検証」（規則が及ばない真偽値・注記の数）も出る。
作業基準日（Issue #11）：各受け渡しの**基準日 ＝ その草案群の作業基準日の最新**（データで決まり、時計に依存しない）を現在日として検査し、
作業基準日を1つ後ろにずらす編集を **100%** 検出することを求める（`as_of_detection_min = 1.0`）。回帰テストでは `require_as_of` を有効にする。

## 限界

- 公式PDFは GitHub に無いため、CI は**引用文がPDFに存在するか**を確認できない。PDFがある環境での `audit_handoff --pdf-dir` が必要。
- 変異テストは「数字を+1」にする編集だけを測る。意味の反転は `flip_sweep` が**既知の言い回し**について測る（未知の言い回しは保留 C の報告のみ）。
- 版管理の回帰は、根拠に保存された引用文から作った版で行う。実際のPDFの版では、レイアウトの違いによる `reworded` が出うる。
