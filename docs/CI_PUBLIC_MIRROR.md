# 公開 CI ミラー（GitHub Actions の代替）

非公開リポジトリの GitHub Actions は無料枠の上限で動かない（`docs/GITHUB_ACTIONS_BILLING_ANALYSIS_20261111.md`）。そこで、**テストを走らせるためだけ**の公開リポジトリ `masatosprojects/SOGH-ci-mirror` を作った（2026-11-12、本人の依頼）。正本ではない。

## 何を公開し、何を外すか
- 公開：コード、テスト、移行 SQL、パッチ、公式情報の調査資料、docs の大半。
- 外す：`strategy/`、`AGENTS.md`、`CLAUDE.md`、`.claude/`、`approvals/`（承認者の実名入り）、`docs/execution-plan/`、夜間・QA の報告類、Issue/PR テンプレート。端末のユーザー名は `USER` に置換。
- 実在の応募者データ・認証情報・本番 DB は元からリポジトリに無い。
- ミラーの workflow は、署名承認まわりのテスト 4 件を除外する（署名者ファイルを外したため 2 件、CI に ssh 署名環境が無いため 2 件）。この 4 件は手元の全件実行で確認する。

## 更新のしかた
`bash scripts/sync_ci_mirror.sh [ref]`（既定 `origin/master`）。パスは作業 PC 用に固定してあるので、環境が違えば先頭の変数を直す。**master が変わるたびに手動で実行する**（自動同期はしない）。枝を指定すれば、マージ前の検査にも使える。

## 限界
- 自動ではない。ミラーの結果を見るのは Claude（失敗は #199 に報告）。
- 公開履歴に、端末のユーザー名の断片を含む一時パスが 1 か所残っている（個人を特定しない）。履歴を書き換えない限り消えない。
- 独立監査は A-15（Antigravity）で行う。
