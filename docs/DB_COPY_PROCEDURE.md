# 実DBのコピーの作り方と、独立監査に必要な入力（Work 向け）

目的：Claude が `python -m src.integration.db_audit <コピー> --target-kind copied_real_db` を実行できるようにする。**実DBを変更せず、GitHub に実DB・秘密情報を保存しない。**
コピーの置き場（GitHub 以外の共有など）は Issue #55 で相談する。

## 1. 必要な入力（W-03）
| 入力 | 内容 | 用途 |
|---|---|---|
| ① DBの独立コピー（`.sqlite`） | 下の手順で作る。**実DBそのものではない** | 全不変条件（DB-01〜12）、構造の確認 |
| ② コピーの SHA-256 とバイト数 | `sha256sum copy.sqlite` | コピーの同一性。Claude の監査レポートに記録される（`copy_identity`） |
| ③ `sqlite3 <db> .schema` の出力（テキスト） | 索引・トリガーを含む | 構造の確認。コピーが無くても構造だけは監査できる |
| ④ 更新前のコピー（任意） | 直近の更新の前に作ったもの（`RevisionStore` の `backup-before-update` など） | DB-09（旧行の保全）を実行できる |
| ⑤ 取得時刻と、コピー元の読み方 | いつ・どのファイルから・どう複製したか | 再現性 |
データが無い項目は `not_run` になる。**実DBが無ければ M1 のゲートは未達のまま**（`not_run` を `pass` にしない）。

## 2. 安全なコピーの作り方（実DBを変更しない）
1. 実DBを使うプロセス（監視・更新）が書き込み中でないことを確認する（本番ワーカー・スケジューラの操作は別途許可が必要。**止める必要があるなら先に相談**）。
2. SQLite の読み取り専用接続で一貫したコピーを作る：
   ```text
   sqlite3 "file:<実DBのパス>?mode=ro" ".backup 'copy.sqlite'"
   ```
   （`.backup` はオンラインバックアップで、実DBの内容を変えない。ファイルを直接 `cp` しない：書き込み途中だと壊れる。）
3. コピーに対して `PRAGMA integrity_check;` が `ok` か確認する。
4. `sha256sum copy.sqlite` を記録する。
5. **機微情報の除去（コピーに対して行う。実DBには行わない）**：次の列には、ローカルのパス（利用者名を含む）が入っていることがある（監査のプライバシー検査が `C:\Users\<名前>\…` を検出する）。コピーでだけ置き換える。
   - `source_documents.local_path`、`legacy_imports.original_path` / `copy_path`、`article_versions.artifact_path`。
   - `update_batches.qa_json`、`legacy_records.record_json`、`legacy_imports.audit_json` にパスやメールアドレスが入っていないか確認する。
   - 除去した列と置換方法を記録する。**除去は、監査が見る列（ID・ハッシュ・本文・record_json の値）を変えない範囲で**（変えたら DB-04・DB-12 の結果が意味を失う）。
6. 除去後のコピーで、もう一度 `integrity_check` と SHA-256 を記録する（除去前後の2つのハッシュ）。

## 3. 送ってはいけないもの
実DBそのもの、API キー・トークン・パスワード・Cookie、原本PDF（`source_documents.local_path` の先）。GitHub には**スキーマ出力（③）と、ハッシュ・行数のレポート**だけを置く。

## 4. Claude が受け取ったあとにすること（変更を伴わない）
1. SHA-256 とバイト数が一致するか確認。
2. `db_audit <コピー> --target-kind copied_real_db [--baseline <④>]` を実行（読み取り専用）、`reports/db-audit/` に結果を保存（コピー自体は保存しない）。
3. `docs/DB_CURRENT_STATE_AUDIT.md` の [R]（確認できない）項目を埋め、`docs/DB_SCHEMA_GAP_ANALYSIS.md` を更新。
4. 実DBの**変更・移行**は、この監査と契約の合意の後（`docs/DB_MIGRATION_POLICY.md`）。
