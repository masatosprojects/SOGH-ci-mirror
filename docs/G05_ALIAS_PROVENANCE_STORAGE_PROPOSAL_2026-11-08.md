# M1.g1／G-05：01（募集人員）の別名の来歴の保管先の最小提案（`pattern`・`source_kind`）｜Claude（2026-11-08）

**ラベル：`CONTRACT_PROPOSAL`・`SELF_TEST`（試作の試験）・`INDEPENDENT_QA_PENDING`・`USER_DECISION_PENDING`。** 移行は**追加していない**（どの DB にも未適用・どこにも未登録）。01 は引き続き **CANNOT_ACCEPT**、M1 は 2/8 NOT_ACCEPTED。
根拠：`G05_OWNER_REVIEW_2026-11-07.md` §12〜13（4 キーのうち `pattern`＝BLOCKED（保存先）、`source_kind`＝BLOCKED（権威ある種別））、候補E の承認（『まず独立照合、足りなければ追記専用の記録を提案』）、Antigravity の最終引き継ぎ（#199 の comment 6721882951、タスク1）。

## 結論（Antigravity の問い『親連鎖か追記専用台帳か』への答え）
- **訂正の履歴（root → 訂正の改訂）は、既存の `parent_evidence_id` の連鎖で足りる。** 01 では `EV-U-8d8e1d177883` の親が `EV-G27-01-e1137e`、p.6、値 16 で、別名 `EV-G27C-01-e1137e` は root に解決される（0003）。ここに新しい保管先は要らない。
- **別名だけが持つ `pattern` は、連鎖には置けない。** 別名は追記専用の表 `evidence_aliases` の 1 行で、連鎖の外にあり、子表も列も無い。→ **追記専用の来歴の束（別名ごとに 1 件）**を別表に置く（下の案 1）。
- **`source_kind`（PDF／HTML の媒体）は、0007 の `source_kind`（文書の役割）では持てない。** → **版つきの追記専用『原典の表現』表**を別に置く（案 2）。役割の列は変えない。
- どちらも**新しい凍結移行（0011 以降）**になる。F-2 アーカイブ（Work の PR #96 候補）は 0011 を使う予定だったので、**どちらを先にするかは番号の判断**（#277 の文書と同じ論点）。

## 案 1：`alias_provenance_bundles`（`pattern` を失わずに残す）
| 列 | 内容 |
|---|---|
| `alias_id` PK, FK → `evidence_aliases` | 別名ごとに 1 件。二重登録は拒否（置き換えない） |
| `bundle_sha256`（64 桁） | 束の正準 JSON の SHA-256。内容アドレス。DB は SHA を計算できないので、**監査（DB-xx）が再計算して照合**する |
| `bundle_json`（`json_valid`） | 必須キー：`original_alias_record`（元の別名レコード。`pattern` と `alias_id` を含む）、`proof_order`、`profile_sha256`、`extractor_version`、`normalizer_id`（`quote_normalized` の版固定にも使える） |
| `recorded_by`・`recorded_at` | 誰がいつ |
- 4 つのガード（UPDATE／DELETE／REPLACE／負の rowid の拒否）は 0010 と同じ形。
- **規則（`pattern` の差が位置の比較から外れる条件）**：その別名に束があり、**検証が空**（SHA 一致・必須キーが揃う・束が同じ別名を指す・`pattern` が残っている）で、かつ**登録しようとする `pattern` が束の `original_alias_record.pattern` と等しい**ときだけ。束が無い／壊れている／違う `pattern` のときは、今と同じく**拒否**（試験で固定）。位置を表すキー（`page`・`quote`・開始終了）の差は今までどおり拒否。

## 案 2：`source_representations`（媒体を版つきで持つ）
| 列 | 内容 |
|---|---|
| `source_sha256`, `rep_version`（PK）、FK → `source_documents(sha256)` | 版は 1 から。訂正は新しい版（旧版は残る） |
| `medium` | `pdf`／`html`／`unknown` のみ。**PDF と HTML は別名にならない** |
| `basis_json` | 根拠：取得時の受領記録（URL・時刻・サイズ・MIME・方針の結果）、固定したバイト列＋パーサーの検証、検証器の版。**ハッシュや拡張子だけ、HTTP の MIME だけ、事実のペイロードの申告だけは根拠にしない**（`G05_OWNER_REVIEW` §13） |
| `recorded_by`・`recorded_at` | 誰がいつ |
- 記録が無い原典の媒体は **UNKNOWN**（拡張子やハッシュから推測しない）。同じ 4 つのガード。
- `source_kind`（0007、文書の役割）は**変更しない**。

## 試作の試験（`tests/test_g05_alias_provenance_prototype.py`、14 件、SELF_TEST）
本物の連鎖 0002〜0009 を適用した**合成の使い捨てDB**に、上の 2 表をテストの中だけで作り（移行ではない）、次を固定した：束が別名に結びつき検証できる／束が無ければ `pattern` の差は拒否のまま（今の状態）／違う `pattern`・SHA 不一致・必須キー欠落・`pattern` 欠落・別の別名を指す束は不十分／存在しない別名への束は拒否・別名ごとに 1 件／束と表現の追記専用（`recursive_triggers` 0／1 の両方、REPLACE、負の rowid）／媒体は UNKNOWN から始まり版で訂正できる／`docx` などの別の値・存在しない原典・版 0 は拒否／0007 の役割の列は変えない。**変異 6 個を検出**（REPLACE ガードの削除、UPDATE ガードの無効化、媒体 CHECK の緩和、SHA 照合の削除、`pattern` 比較の削除、媒体の推測）。

## 本人／Work の判断が要る点
1. **保管先の形**：案 1・案 2 を移行として登録するか（候補E の続き）。登録するなら、番号（0011：来歴／原典の表現、F-2 アーカイブは後ろへ）と、一つの移行にするか二つに分けるか。
2. 束の**作成者**：誰が束を作り、`recorded_by` に何を入れるか（Work の抽出器か、Claude の登録関数か）。能力は認証ではない（D2／G-08）。
3. 媒体の `basis_json` の**必須項目**（取得の運用の判断を伴う）。
4. それまで、`pattern`・`source_kind` の差は**拒否のまま**（今のコードは変えない）。

## 限界・NOT_RUN
- 本物の移行ではない。実コピー・実DBへ適用していない。Antigravity の独立QAは未実施（g1 の p.6 は、これまで Work の保存記録どうしの整合の確認で、**PDF そのものの文字列照合は未了**）。
- `quote_normalized`・`section` の規則は確定済みで未実装（保存先の判断を待たずに実装できるが、01 の受容には 4 件すべてが要る）。
- GitHub Actions（課金によりジョブ未開始）、Windows 以外・Python 3.11。
