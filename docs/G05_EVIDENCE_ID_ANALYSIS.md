# G-05 根拠IDの重複：調査結果と解決案

Issue #55 で見つかった、一般選抜の6事実が2つのID空間（`EV-G27-*`、`EV-G27C-*`）にある問題の調査。**Work のコード・データは変更していない**（読み取りと独立の比較のみ）。**推奨案は提案（proposed）で、Work の合意まで契約にしない。**
試験：`tests/test_evidence_identity.py`、実装：`src/db_contract/identity.py`、CI の警告：`src/regression/fullview.py`（`evidence_identity`）。

## 1. 調査結果（コードとデータから確認）
| 問い | 結果 | 根拠 |
|---|---|---|
| 同じ論理事実か | **はい**。大学・学部・方式・年度・原典（SHA `e1137e…`）・fact_key・値・範囲が一致。02〜06 は引用位置も同一（完全な重複）。**01（募集人員）だけ引用位置が違う** | `tests/test_evidence_identity.py`、`reports/db-audit/audit_all_deliveries_loaded.json` |
| 異なるIDが付いた経緯 | 根拠IDは `EV-<profile code>-<連番>-<原典sha6>`（`extract.py:89`）。**内容ではなく、プロファイルの `code` と抽出順で決まる**。`samples/general` を作ったプロファイル（`tsukuba-klis-general-2027.json`）の `code` は `G27C`、DBの基底状態を作った以前の抽出は `G27`。同じ事実を別の `code` で再抽出すると、新しいIDになる | コード（`extract.py`）、プロファイルの設定 |
| 全体ビューと差分exportの関係 | 全体ビューと基底状態は `EV-G27-*`、`samples/general/claude-compatible-export.json` は `EV-G27C-*`。**2つのIDは別の納品の中にあり、どちらかが他方を置き換えた関係ではない** | データの比較 |
| 記事は両方のIDを引用しているか | **していない**。差分exportの記事3本は G27C だけ、全体ビュー・基底状態の記事は G27 だけを引用 | 試験 `test_no_article_cites_both_id_spaces…` |
| 01 の引用位置が違う理由 | 募集人員の引用位置は以前の抽出が誤っており、訂正の改訂 `EV-U-8d8e1d177883`（`parent = EV-G27-01`）が正しい位置（p.6）を持つ。`EV-G27C-01` は訂正後の位置。**値は同じ** | データの比較 |
| 実際に何が壊れるか | 全納品を1つのDBに入れると `UNIQUE(case_id, source_sha256, fact_key)` が2つ目を拒否する。**ID再利用の検査はIDが違うので見えない**。同じキーを共有する別の事実は、リポジトリ内に**他に無い**（現行のキーが正当な独立の事実を拒んだ例は見つかっていない） | `reports/db-audit/`、試験 |

## 2. 論点：UNIQUE(case_id, source_sha256, fact_key) をどうするか
**維持する・削除する、と決めつけない。** 実験（`tests/test_evidence_identity.py`）で確かめた：
- 現行のキーは、**同じ資料にある同じ fact_key の独立した事実**（たとえば募集人員が2つの枠で2回出る）も拒否する。今は該当が無いが、将来の資料で起こりうる。
- 引用位置（locator）をキーに含めると、独立した事実は保存でき、同じ事実の二重登録は拒否できる。
- ただし位置が訂正された同じ事実（01 の p.5→p.6）は、位置が違うのでキーでは別物になり、**キーだけでは見つからない**。値と位置を比べる指紋の比較が要る。
- 逆に、値が違うのに同じ位置を指す2つは**矛盾**で、別名にしてはならない。

## 3. 提案（Work の合意が要る）
1. **事実の同一性を、内容で定義する**：`fingerprint = (case, source sha256, fact_key, 正規化した値, locator)`。`locator` は proofs の（ページ、正規化した引用）の集合。正規化は NFKC・空白除去。
2. **分類**（`src/db_contract/identity.py`）：`duplicate`（値も位置も同じ）、`same_value_moved`（値が同じで位置が違う＝位置の訂正）、`independent`（値も位置も違う＝別の事実）、`conflict`（値が違うが位置が同じ＝矛盾）。
3. **別名の表**（`evidence_aliases(alias_id PK, evidence_id FK, reason)`）：`EV-G27C-0n → EV-G27-0n`。**旧IDを上書き・改名しない**。残すIDは、すでに記事・DB・履歴が使っているもの（全体ビューの `EV-G27-*`。`EV-G27-01` の有効版は訂正の改訂 `EV-U-8d8e1d177883`）。別名は `duplicate` と `same_value_moved` だけに付け、`independent` と `conflict` には付けない。
4. **キーの粒度**：`UNIQUE(case_id, source_sha256, fact_key, locator_hash)`（`locator_hash` は locator のハッシュ）への変更を検討。ただし位置の訂正は別名で扱う（キーでは見えない）。**変更は Work の合意と、コピーでのドライラン・`db_audit --baseline` のあと。**
5. **IDの生成**：`EV-<code>-<連番>-…` を、内容から決まる論理ID（fingerprint のハッシュ）に基づくIDにする、または少なくとも**プロファイルの `code` を再抽出で変えない**（変えるなら別名を同時に作る）。差分export（`samples/general`）は、DBのIDで出す（互換のためだけに別のIDを付けない）。

## 4. 今回実装したこと（Claude 担当の範囲）
- `identity.py`：fingerprint・分類・別名の提案（改名も削除もしない）。
- **CI（`fullview`）**：全体ビューと過去の納品の間で、同じ事実が2つのIDにあれば**警告**として別名の提案つきで出す。**矛盾（`conflict`）は失敗**にする。現状は重複5組（全体ビューに残る `EV-G27-02〜06` と `EV-G27C`）で、失敗ではなく警告。6組目（`EV-G27-01`、基底状態）は、全体ビューでは訂正の改訂に置き換わっている。
- 負例の試験：キーが粗すぎる／細かすぎる、矛盾は別名にしない、別の資料・fact_key・サイクル・改訂はまとめない、空白と全角の揺れ、2つのID空間の記事の引用。

## 5. Work への依頼（Issue #55、`docs/WORK_BACKLOG.md` W-04）
1. 方針：1事実1ID（上の3・5）にするか。
2. `UNIQUE` の粒度の変更に同意するか。
3. `EV-G27C-*` の `samples/general` を、全体ビューの `EV-G27-*` に揃えて出し直すか、別名表を足すか。
**Claude は Work のデータ・ID を変更しない。**
