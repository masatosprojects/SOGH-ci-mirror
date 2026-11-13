# SOGH｜ChatGPTコピペ不要のエージェント起動案（2026-11-08）

> **状態：本人承認済み（2026-11-08、SOGH05のA選択）／端末実導入は未確認**。対象は2AI用手動起動スキルのみ。Raspberry Piの常時稼働・監視、新しいモデル推論、本番DB変更、OS自動起動は未承認。

## 基本方式：共通GitHub原本 + 端末別1回限り登録スキル
- メインPCのClaude Code：`.claude/skills/sogh-resume/SKILL.md` → セッション内の固定 `/sogh-resume`。
- ゲーミングPCのGoogle Antigravity：`.agents/skills/sogh-resume/SKILL.md` → セッション内の固定 `/sogh-resume`。
- スキル本文はGitHubに保存。人は**各PCで最初のセットアップ／以降は短いローカルコマンドのみ**を実行し、通常ChatGPTチャットで長い実行文を表示・転送しない。
- スキルは最新master、#199の**最新コメント**、#214、自担当PR/head、本人承認範囲を読んで自律計画最大2件。ACK/RESULTを書き、本人未承認の本番/モデル/課金/マージは拒否する。
- 1回の配置で動くことを保証せず、両PCでリポジトリ取得・GitHub認証・各IDEのスキル検出を確認する必要がある。作業中のブランチや未コミット編集を`git reset`/`git clean`/`git pull`で無断上書きしない。
- **GitHubへの掲載のみでセッションが起動・進行するわけではない**。固定ショートカットを押す／`/sogh-resume`を入力する「現地での1アクション」は残る。ユーザーのChatGPTチャットを経由する必要はない。
- 将来ダブルクリック起動を検討する場合、メインPC Claude Code CLIなら単発コマンドのラッパー案、Antigravityは実利用中のIDE/アプリ/CLIの対応確認が必要。**このPRでは起動スクリプト・OS自動起動・バックグラウンドポーリングを導入しない**。

## 本人の指示・出所・安全の区別
`USER_DIRECT`（本人の実際の承認）と`APPROVED_STR`と`AI_PROPOSAL`を分離。固定スキルの起動は「既存の承認済み安全タスクの再開」という運用開始の指示に限定し、個別の実DB/高負荷操作・技術マージ・新サービス公開を許可しない。

## 運用開始前の確認
1. 本PRに含まれる2つの`SKILL.md`の内容と権限・対象範囲を人間がレビューする。
2. **PR #275の2AIスキル導入について本人が明示許可済み**。これは他の技術PRやRaspberry Pi実運用のマージ/起動許可ではない。
3. 両端末でGitから取り込み、各アプリの`/`候補に`sogh-resume`があるか確認。失敗時は`ACCESS_BLOCKED`として手順を修正する。
4. 既存のコマンドを1回実行して、Issue #199に各AIがACK/RESULT（固定HEAD付き）を書けることを確認する。実装者の自己試験と独立QAとM1正式受容を混同しない。


## 初回インストール（Windowsの各PCで一度だけ。ChatGPTチャットは不要）
1. **メインPC**のClaude Code作業リポジトリ、**ゲーミングPC**のAntigravity作業リポジトリをそれぞれ開き、対象リポジトリが`masatosprojects/SOGH-collab`であることを確かめる。作業ツリーの保護が優先：`git status --short`と`git branch --show-current`で未保存・未コミット変更を確認し、`git remote -v`でGitHub接続を確認。
2. 各PCのリポジトリルートで`git fetch origin`（取得のみ、作業ツリーは上書きしない）。`git log -1 --oneline origin/master`で新ルールを含むコミットがあることを確認する。リモートに接続できない場合は`ACCESS_BLOCKED`で終了する。
3. すでに作業ブランチが`master`を含み、次のファイルが見えていれば追加のコピーは不要。
   - Claude Code：`.claude/skills/sogh-resume/SKILL.md`
   - Antigravity：`.agents/skills/sogh-resume/SKILL.md`
   **現在の作業ブランチにファイルがまだ無い場合だけ**、対象パスがローカルに存在しないことを確認し、当該PCのリポジトリルートで以下の**片方だけ**を実行する（他のコード・未コミット変更に触れない）：
   - Claude Code：`git restore --source=origin/master --worktree -- .claude/skills/sogh-resume/SKILL.md`
   - Antigravity：`git restore --source=origin/master --worktree -- .agents/skills/sogh-resume/SKILL.md`
   ローカルの同名ファイルが存在する場合は**上書きせず停止して差分を確認**。このファイルのみの作業ツリー取込は、他の未マージPRの`master`への統合ではない。ただし現作業ブランチでは未コミットファイルとして見える場合があるため、後続作業前に状態を確認する。
4. Claude Codeは既存セッションで`/sogh-resume`の候補を確認。追加した最上位スキルがセッションで認識されない場合は、**現在の作業状態を保存してから**Claude Codeを通常再起動する。Antigravityはプロジェクト・ワークスペースを開き、エージェント画面のスキル一覧で`sogh-resume`が表示されるか確認。必要なら通常の新しいエージェント会話を作る。
5. 双方で`/sogh-resume`を**手動で一度**呼び出し、GitHub Issue #199に最新master SHA、読んだ規約、次タスク/待機理由を含む本人ACK/RESULTが残ることを確認する。表示されない場合やGitHubアクセス不可なら実行を捏造せず`ACCESS_BLOCKED`として状況を記録する。

※`git reset --hard`、`git clean`、既存の未保存ファイル上書き、スキルを読み込ませるためだけの技術PRのマージは行わない。学習させたいワークスペースのルートがGitHubのクローンと異なる場合は、それぞれの製品のスキル検出ルートを先に確認する。

## 最終的にチャット上に出すのは数行だけ
「Claude: 次候補／Antigravity: QA結果／Work: 休止・再開必要性／Pi: 未起動。正本リンクはIssue #199と固定PR。追加のChatGPT→各PCコピーは不要。」
