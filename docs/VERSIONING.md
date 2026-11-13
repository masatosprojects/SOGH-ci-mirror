# 公式情報の版管理と、変更の影響範囲の特定

実装: [src/versioning/](../src/versioning/)　Issue: #15（版管理・差分）、#16（影響の特定）、#17（監視＝Work）
テスト: [tests/test_versioning.py](../tests/test_versioning.py)、[tests/test_regression_work_v02.py](../tests/test_regression_work_v02.py)

## 目的

公式の募集要項は**更新・訂正**される。保存した版のまま記事を出すと、古い数字を載せる。
このモジュールは、**新しい版を受け取ったとき、どの事実と記事を確認し直すべきか**を決める。
何も公開・編集しない（「何を再確認するか」を出すだけ）。

## 流れと担当

```
[Work] 公式サイトを監視し、新しい版（PDF・訂正告知）を取得 ──► 版のJSON（SourceSnapshot）を出力 … #17
        │
        ▼  Issue / PR で通知（自動公開はしない）
[Claude] python -m src.versioning.diff    --old 旧版 --new 新版      … どこが変わったか
[Claude] python -m src.versioning.impact  --export 根拠と記事 --new 新版 …  どの事実・記事に影響するか
        │
        ▼
[Work] 影響を受けた事実を再抽出・記事を再生成 → 監査（audit_handoff）→ PR
```

## 版の JSON（SourceSnapshot）契約

```json
{
  "schema_version": 1,
  "source_id": "tsukuba-klis-ac-2027",
  "url": "https://…/AC_youkou2027_sec.pdf",
  "sha256": "<原本ファイルのsha256（64桁）>",
  "retrieved_at": "2026-11-01",
  "pages": ["1ページ目のテキスト", "2ページ目のテキスト", "…"],
  "supersedes": ["<この版が置き換える旧版のsha256>"],
  "edition_note": "訂正版（任意）"
}
```

- `pages[0]` が1ページ目。PDFの表示ページ番号（`#page=N`）と同じ数え方。
- `supersedes`：URLが変わる版（ファイル名にハッシュを含む等）を、旧版の根拠に結び付けるために使う。
- 訂正告知などのHTMLも同じ形で表せる（`pages` に本文を1要素以上）。
- **PDF全文を含むため、`.gitignore` で管理対象外**（`snapshots/`、`*.snapshot.json`）。権利と容量のため、GitHubに上げない。
  リポジトリに残すのは、URL・sha256・必要最小限の引用文（根拠レコードの `proofs`）だけ。
- 作成：`python -m src.versioning.snapshot <file.pdf> --source-id … --url … --retrieved-at … --out snapshots/….snapshot.json`（`pymupdf` が必要）

## 根拠レコードとの対応

根拠レコードは、引用文（`proofs[].quote`）と、その位置（`proofs[].page`）、出典（`source_url`、`source_pdf_sha256`）を持つ。
新しい版との対応づけは、①版のハッシュ（`source_pdf_sha256`、HTML の告知は `source_sha256`）が新版の `sha256` または `supersedes` に含まれる、②`source_url` が一致、の順。
どちらにも当たらない根拠は **`unassessed`（確認できない）** として必ず別枠に出す。**最新だと仮定しない。**

## 判定（引用文ごと → 根拠 → 記事）

| 状態 | 意味 | 記事への影響 |
|---|---|---|
| `intact` | 引用文が、同じページに一字一句残っている | なし |
| `moved` | 引用文は残るが別のページへ移った（ページ番号がずれた） | **確認**（記事・出典リストの「p.N」「#page=N」が古くなる） |
| `page_changed` | 引用文は残るが、同じページの別の箇所の数量・日付が変わった（**旧版も渡したとき**のみ判定） | **確認**（変わった箇所が記事の事実とは限らない） |
| `reworded` | 引用文は無いが、近い文がある（文言の変更） | **再作成**（`republish_required`） |
| `value_change` | 数字・日付以外は同じ文が見つかり、**数字・日付だけが違う**（事実が変わった） | **再作成** |
| `missing` | 近い文も無い（削除または書き換え） | **再作成** |
| `unassessed` | 比べる新版が無い／引用文が無い | **未確認**（公開前に確認が必要） |

根拠は、引用文のうち最も重い状態を取る。記事は、引用している根拠のうち最も重い状態を取る
（`republish_required` ＞ `unassessed` ＞ `review` ＞ `ok`）。

## 終了コード

- `diff`：版が同一なら 0、何か違えば 1。
- `impact`：`intact` 以外が1つでもあれば 1（`moved` だけでも、記事のページ番号が変わるため 1）。
  未確認だけが残る場合は 0。`--require-all-assessed` を付けると 2（公開前のゲートに使う）。

## 限界（正直に）

- 判定は**保存してある引用文**を軸にする。引用文の**外**で事実が変わっても、旧版を渡さない限り見えない（旧版を渡すと `page_changed` で気づける）。
- 表の列ずれ、画像だけのPDF（OCR）、段組みの変更で、同じ内容でも文字の並びが変わると `reworded` / `missing` になる。**変更の誤検出は許容し、見逃しを避ける**方針。
- 数字・日付が変わった `value_change` は、引用文内の数字を単位なしで比べる。意味（「5名→6名」が増員か訂正か）は判断しない。
- 公式サイトの**どこを見るか**（更新確認、正誤表ページ、お知らせ）は収集側（Work、#17）の責務。ここは取得済みの版を比べるだけ。
- 最新性の確認は、版が渡されて初めて成立する。**渡されない根拠は `unassessed` のまま**であることを、公開前に必ず確認する。

## 実データでの動作例

Work の実データ（30事実・4草案）に、「筑波大学 知識情報・図書館学類の募集人員 5名→6名」という**模擬の改訂**を入れた結果は
[reports/versioning-demo/](../reports/versioning-demo/)。その事実は `value_change`、それを引用する記事は `republish_required`、
同じページの他の4事実は `page_changed`（それらだけを引用する記事は `review`）、残り25事実と慶應の記事は影響なしと判定される。
