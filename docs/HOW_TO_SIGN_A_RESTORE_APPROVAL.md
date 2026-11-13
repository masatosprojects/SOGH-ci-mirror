# 復元の承認に署名する手順（ユーザー向け）

**今すぐ署名するものは何もありません。** 署名するのは、Work の復元道具が作った**承認マニフェスト**（署名なしのコミット）が承認用ブランチに出てからです。そのとき署名すべき場面は 2 つ：F-2 の状態 B（30 行の復元）と、F-2 の受容。F-2 の前提（`0010` の SQL 案）はまだ出ていません（`docs/F2_G2_MIGRATION_AND_DB17_CONTRACT.md` の手順 2）。チャットで「承認」と書くだけでは、署名の代わりになりません（同じ GitHub アカウントを全 AI が使うため。`docs/RESTORE_APPROVAL_MANIFEST_2026-11-07.md` §1）。

## 署名の前に受け取るもの（Work の報告から）
承認用ブランチの名前、`restore_id`、`archive_sha256`、`source_db_sha256`（それぞれ 64 桁の英数字）。**ハッシュは Work の報告から写してください。マニフェストの中からは写さない**（署名しようとしているファイルを、そのまま信用しないため）。

## 手順（あなた自身の PowerShell で。鍵やパスフレーズは誰にも渡さない）
```powershell
cd <SOGH-collab のクローン>            # 例：C:\Users\USER\sogh-sign の元のクローン
git fetch origin
git switch <承認用ブランチ>
python scripts/sign_restore_approval.py --restore-id <restore_id> --archive-sha <Work の報告の値> --source-db-sha <Work の報告の値> --check
```
`--check` は**何も署名しない**確認です。次が表示されます：復元 ID／アーカイブと元 DB のハッシュ／items の件数と種別／`items_digest`（再計算して一致）／承認者（`approver-1`）／note。**ここを読んで、Work の報告と同じか確認**してください。`STOP:` と出たら**署名せず**、理由を Claude に伝えてください（ブランチが違う・他のファイルが混ざっている・ハッシュが違う、など）。

問題なければ、同じコマンドから `--check` を外して実行します：
```powershell
python scripts/sign_restore_approval.py --restore-id <restore_id> --archive-sha <…> --source-db-sha <…>
```
`SIGN <restore_id>` と**そのとおり**入力すると、git があなたのパスフレーズを聞きます（入力は画面に出ません）。成功すると `Signed and verified.` と `approval_ref: sha256:…@…` が出ます（検証器が、固定した指紋と署名を確認済み）。最後に、あなたが押します：
```powershell
git push --force-with-lease origin <承認用ブランチ>
```
（署名でコミットを作り直すため、`--force-with-lease` が要ります。このブランチだけです。）

## 守ること
- 署名は**1 回の復元ごと**。使い回さない。ブランチは master にマージしない（承認用）。
- 署名は「あなたが承認した」ことを示すだけで、**内容の正しさは示しません**。件数・種別・ハッシュを読むのが承認の中身です。
- 取り消しは、DB に `restore_revocations` を追記（Claude に依頼）。再開には新しい `restore_id` と新しい署名が必要です。
- 練習：前回の `DRYRUN-0001` と同じ流れです。心配なら、先に `--check` だけで試してください。

## 試験
`tests/test_sign_restore_approval.py`（使い捨ての鍵と合成データのみ、12 件）：正常、`--check` は署名しない、確認の言葉が違えば署名しない、ハッシュが違えば質問の前に停止、master 上・未コミットの変更あり・他のファイルが混ざる・既に署名済み・承認者違い・items_digest 不正は停止、固定した指紋が署名の鍵と違えば検証が失敗、`.pub` 以外の鍵は拒否。あなたの実際の鍵と承認は使っていません。
