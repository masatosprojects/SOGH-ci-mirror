# 復元の承認記録 — ユーザーの署名つきコミット（契約案、2026-11-07、Claude）

**決定（ユーザー承認 2026-11-07、チャット）**：復元の承認者は**ユーザー本人**。承認の証拠は、**ユーザーの SSH 鍵で署名したコミットに入れた承認マニフェスト**。
**状態**：契約案（`CONTRACT_PROPOSAL`）と参照検証器（`src/db_contract/approval_manifest.py`、`SELF_VALIDATED`）。DB には何も適用しない。F-2 の復元の承認そのものではなく、**承認の形式**の確定である。M1 は 2/8、NOT ACCEPTED。

> **運用の状態（重要）**：ユーザーは Claude との会話で、承認の形式として「署名つきコミット」を**2 回承認した**（2026-11-07：提案への「Yes, signed commit」、指令票 #203 の実行後の再確認への「進める」）。指令票 [#203](https://github.com/masatosprojects/SOGH-collab/issues/203) は「ユーザーが別途方針承認するまで、新しい署名運用・本番表の導入や承認の代理実行をしない」としていた。この 2 回の承認は会話上のもので、**GitHub 上では検証できない**ため、指令塔側でも確認してほしい。これを受けて、**本ブランチを提案の PR（未マージ）として提出する**。PR の範囲は、マニフェストの形式・検証器・試験・文書だけで、署名鍵の作成・署名・DB への導入・復元の承認は一切含まない（鍵の作成と署名はユーザー本人が自分の端末で行う。§4）。

## 1. なぜ署名か
Work・Claude・Antigravity・ユーザーは**同じ GitHub アカウント**で投稿する。Issue のコメントでは、誰が承認したか区別できない。SSH 署名つきコミットは、**秘密鍵を持つ者だけ**が作れる。AI は秘密鍵を持たない。

### 1.1 脅威と権限境界の整理（#203 P0-1 の求め）
| 脅威 | 例 | 対策／残るリスク |
|---|---|---|
| 同一アカウントによるなりすまし | AI が「ユーザーが承認した」とコメント・コミットする | 署名つきコミット（ユーザーだけが持つ鍵）。コメントや署名なしコミットは承認とみなさない（`not_signed`）。 |
| 他の鍵での署名 | AI が自分の鍵で署名し、`allowed_signers` にその鍵を足す | 検証は**固定された指紋**との完全一致だけを認める（`wrong_signer`）。指紋はレビューされた文書とコードにのみ置く。 |
| 署名後のすり替え | 署名済みコミットの後でマニフェストを編集 | 参照にマニフェストの SHA-256 とコミットを束ねる（`manifest_changed`）。 |
| 署名に便乗した混入 | 署名コミットに別のファイルを足す | 署名コミットは 1 ファイルのみ（`commit_not_only_the_approval`）。 |
| 別の復元への流用 | 承認を別のアーカイブ・元 DB・復元 ID に使い回す | `archive_sha256`・`source_db_sha256`・`restore_id` の一致を要求（`approval_mismatch`）。 |
| 秘密鍵の奪取 | AI が動く同じ PC のディスクから鍵を使う | パスフレーズ必須、AI セッション中は `ssh-agent` に載せない、可能なら別端末・ハードウェア鍵。**完全には防げない（残るリスク）。** |
| 信頼の根の書き換え | 固定した指紋の差し替え | ユーザーがマージした PR のみ。コードは指紋を引数で受け取り、検証対象のファイルから読まない。 |
| 内容の誤りを署名する | ユーザーが確認せずに署名 | 署名は「誰が」であり「正しさ」ではない。§4③ の差分確認が承認の中身。 |

## 2. 承認マニフェスト（`approvals/restore/<restore_id>.json`）
```json
{
  "schema": "sogh.restore_approval.v1",
  "restore_id": "R-F2-001",
  "kind": "f2_recovery",
  "decision": "approve",
  "archive_sha256": "<F-2 アーカイブの SHA-256>",
  "source_db_sha256": "<元 DB（v03 写し）の SHA-256>",
  "items": [{"kind": "article_version|evidence_version|citation", "id": "...", "digest": "<行ダイジェスト>"}],
  "items_digest": "<items の正規化 JSON の SHA-256>",
  "approved_by": "<署名者の principal（allowed_signers の名前）>",
  "approved_at": "2026-11-07T20:00:00+09:00",
  "note": "<人が読む説明>"
}
```
- キーは**ちょうどこの 11 個**。`restore_id` はファイル名と同じ。`items` は空でなく重複なし。`items_digest` は `items` の正規化 JSON（キー順・区切り固定）の SHA-256。
- `items` は、復元道具（Work）が F-2 のアーカイブから**機械的に生成**する。ユーザーは §4 の手順で内容を確認してから署名する。
- DB の `restore_events.approval_ref` は `sha256:<マニフェスト全体の SHA-256>@<署名コミット（40 桁）>`、`approved_by` はマニフェストの値。

## 3. 検証（`verify_approval`、1 つでも失敗すれば拒否。部分合格を信用しない）
1. `approval_ref` の形式。2. 署名コミットの中のマニフェストが、`approval_ref` のダイジェストと**バイト一致**（後からの編集を拒否）。3. コミットに**良好な SSH 署名**があり、鍵の指紋が**固定された信頼の根（pinned fingerprint）と完全一致**（`allowed_signers` に別の鍵があっても、それだけでは足りない）。4. そのコミットが**そのマニフェスト 1 ファイルだけ**を変更（署名の陰に他の変更を隠せない）。5. スキーマが正しく `decision: approve`、`restore_id` = ファイル名。6. マニフェストの `restore_id`・`archive_sha256`・`source_db_sha256` が、**これから復元するもの**と一致。7. 署名者の principal = `approved_by`。8. （任意）コミットが指定の ref（例：`master`）の祖先（レビューを通っている）。
拒否の符号：`bad_ref`・`bad_trust_root`・`bad_input`・`manifest_missing`・`manifest_changed`・`not_signed`・`wrong_signer`・`commit_not_only_the_approval`・`manifest_invalid`・`not_approved`・`approval_mismatch`・`signer_not_approver`・`not_reviewed`。

## 4. ユーザーの設定と署名の手順（ユーザー自身の PowerShell で。AI に鍵を渡さない）
**① 鍵を作る（パスフレーズを必ず設定）**
```powershell
ssh-keygen -t ed25519 -C "sogh-approver" -f "$env:USERPROFILE\.ssh\sogh_approver"
ssh-keygen -lf "$env:USERPROFILE\.ssh\sogh_approver.pub"
```
2 行目の出力の `SHA256:…`（**指紋＝公開情報**）をチャットで教えてください。それが信頼の根（pinned fingerprint）になります。**秘密鍵（`sogh_approver`、`.pub` のないほう）は誰にも渡さない。チャットにも貼らない。**
**② 公開鍵の登録**：`approvals/allowed_signers` に `<principal> namespaces="git" <.pub の内容>` の 1 行（AI が PR で提案し、ユーザーがレビューしてマージ）。指紋はコードの設定と文書に固定する。
**③ 署名する**：AI または Work が作った承認マニフェスト（署名なし）の PR ブランチをユーザーが確認し、確認後に**ユーザー自身が**署名コミットを作る。
```powershell
git switch <承認用ブランチ>
git diff origin/master -- approvals/restore/<restore_id>.json   # items の件数・種別・archive_sha256・source_db_sha256 を読む
git -c gpg.format=ssh -c user.signingkey="$env:USERPROFILE\.ssh\sogh_approver.pub" commit -S -m "approve restore <restore_id>"
git push
```
コミットに入れるのは**そのマニフェスト 1 ファイルだけ**（他を含めると検証が拒否する）。署名は 1 回の復元ごと。**使い回さない。**
**④ 取り消し**：DB に `restore_revocations` を追記する（読み取りは直ちに拒否される）。再開には新しい `restore_id` と新しい署名が要る。

### 4.1 固定した承認者（2026-11-07、ユーザーが鍵を作成）
- ユーザーが自分の PowerShell で ed25519 の鍵を作り、**公開鍵と指紋だけ**をチャットで Claude に渡した。秘密鍵とパスフレーズは受け取っていない。パスフレーズが設定されていることは、ユーザーの画面（`ssh-keygen -y` がパスフレーズを求めた）で確認された。Claude はこれを独立には観測できない。
- 指紋：`SHA256:ACP/j/RQUvjKDtXzMhZx85wegj42Tf6Ds1OpVgcOyDY`。Claude が貼られた公開鍵から再計算して一致を確認した。署名者は the approver（ユーザー本人の指定）。ssh の許可リストは空白で項目を区切るため、識別子は空白を含まない `approver-1` とし、本名は本記録とマニフェストの `note` に書く。
- 置き場：`approvals/allowed_signers`（公開鍵 1 行、`namespaces="git"`）と `src/db_contract/approval_trust.py`（指紋と principal の定数）。試験 `tests/test_approval_trust.py` が、定数と許可リストの鍵の指紋が一致することを確認する。
- **この PR をユーザーがマージして初めて、この指紋が信頼の根になる。** マージ前は提案であり、署名運用は始まっていない。実際の承認マニフェスト（F-2 など）はまだ存在せず、署名は 1 件もされていない。

## 5. 限界と残るリスク（正直な記録）
- **秘密鍵が AI の動くこの PC のディスクにある**と、シェルを持つ AI がそれで署名できてしまう。対策：パスフレーズを必ず設定し、AI のセッション中は `ssh-agent` に鍵を読み込まない。最も強いのは、別の端末（またはハードウェア鍵・`ed25519-sk`）で署名すること。
- 署名は「**この鍵の持ち主が署名した**」ことを示すだけで、**内容が正しいこと**は示さない。ユーザーが §4③ の差分（件数・種別・SHA）を読むことが承認の中身である。
- 信頼の根（指紋）を書き換えられる者は承認を偽造できる。指紋は**レビューされた文書とコード**に固定し、`approvals/` のファイルから読まない（検証器は指紋を引数で受け取る）。変更はユーザーがマージした PR のみ。
- 検証は `git verify-commit --raw` の出力形式に依存する（git 2.53.0 で確認）。git の更新で形式が変わったら、検証は**拒否**側に倒れる（承認とはみなさない）。
- 参照検証器は書き込みも復元もしない。**復元の道具（Work）が、書き込みの前に `verify_approval` を呼ぶこと**が受容条件。リーダー（`read_cited_evidence`）は毎回は検証せず、`restore_events` が検証済みの承認でしか作られないことに依拠する。独立 QA が連鎖（マニフェスト→コミット→指紋→`restore_events`）を確認する。

## 6. 試験（`tests/test_approval_manifest.py`、使い捨ての鍵と合成データのみ）
正常、未署名、別の鍵（`allowed_signers` にあっても拒否）、`allowed_signers` にない鍵、署名後の編集、他のファイルを含む署名コミット、マニフェスト不在、アーカイブ／元 DB／復元 ID の不一致、principal の不一致、祖先条件、参照・信頼の根・入力の不正、無効・非承認のマニフェスト 15 種。ユーザーの実際の鍵は使わない。
