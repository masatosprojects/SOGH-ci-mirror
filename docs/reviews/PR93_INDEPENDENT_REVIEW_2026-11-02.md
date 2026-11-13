# PR #93 の独立レビュー（Claude、2026-11-02）

> **再レビュー（head `20192313457cd28cfdabe1551c35c90dc111b073`）：`PASS_WITH_WARNINGS`。** Work が F-1・F-2a・F-2b・F-3 を修正した。私は Work のファイルを編集せず、修正後の head を新しい使い捨て領域で実行して確認した（末尾「再レビューの記録」）。以下の本文は**初回（head `cb03ff8`）の記録**で、F-1〜F-3 は修正済み。残る F-4・F-5・F-6 は情報（未対応）。

対象：PR #93「[Work] 凍結移行の独立再実行・更新パッチ統合・架空面接/報告UI」、**head `cb03ff821b46479be3a62776512d1b8ccf75550a`**（base `5db1de0`、CI 3 ジョブ success）。
レビュー者：Claude（独立 QA）。**Work のファイルは編集していない**（PR の checkout を detached の読み取り専用 worktree として使い、再現は Claude 側の使い捨て領域で行った）。Work が提出したコードを書き換えてから試験した結果は含まない。

## 判定

| 範囲 | 判定 | 要点 |
|---|---|---|
| `prepare_isolation.py`・`work-current-stage1.patch`・`preconditions.json` | **PASS_WITH_WARNINGS** | 事前条件・出力先の拒否・原本不変・適用結果は確認できた。警告 F-2a／F-2b |
| 更新トランザクション（`finalize`）と接続条件 | **PASS_WITH_WARNINGS** | 異常系はすべて全部戻る。D2 の限界は変わらない（警告として据え置き） |
| `--reason-json` | **PASS_WITH_WARNINGS** | `null` の扱いに警告 F-3 |
| `demo/`（ローカル Web UI） | **CHANGES_REQUESTED（小・1 件）** | **F-1**：報告フォームで「個人」の面接形式を選べない |
| **PR 全体** | **CHANGES_REQUESTED** | F-1 を直せば、他の再レビューなしに `PASS_WITH_WARNINGS` へ変更する（F-2a・F-2b・F-3 は推奨） |

M1 は 2/8（g4・g8）、NOT ACCEPTED のまま。この判定は M1 の受け入れ判定ではない。

## 指摘（Work への修正依頼）

| ID | 重大度 | 内容 | 最小の再現 | 期待 | 試験 |
|---|---|---|---|---|---|
| **F-1** | **要修正** | `demo/index.html` の面接形式の `<select>` が `<option value="unknown">覚えていない</option value="individual">個人</option>` と書かれている。ブラウザーは不正な終了タグで最初の option を閉じ、`個人` を捨てるため、`individual` の選択肢が**存在しない** | 画面の「受験報告を試す」で形式の選択肢を確認（Browser pane で `unknown／group／presentation_then_qa／online／other` の 5 件のみ） | `<option value="unknown">覚えていない</option><option value="individual">個人</option>` | `test_known_issue_pr93_f1_…` |
| F-2a | 警告 | 途中の手順が失敗すると（例：コピー元に `config` が無い）終了コードは非 0 だが、作りかけの出力ディレクトリが失敗の印なしで残る（再実行は拒否される） | `config` を除いた複製元で実行 → 出力に 38 ファイル | 出力を削除するか、失敗の印を置く | `test_known_issue_pr93_f2a_…` |
| F-2b | 警告 | `git apply` が `core.autocrlf` に従うため、同じ入力でも出力は `true` で CRLF、`false`／`input` で LF になる（本文は同じ）。出力の生ハッシュが機械間で再現しない | `GIT_CONFIG_KEY_0=core.autocrlf` を `true`／`false` にして同じ入力を実行 | `git -c core.autocrlf=false apply` | `test_known_issue_pr93_f2b_…` |
| F-3 | 警告 | `--reason-json` に **`null` だけのファイル**を渡すと「理由なし」と同じに扱われ、更新が理由なしで始まる（他の非オブジェクトは終了コード 2 で拒否） | `reason.json` の内容を `null` にして実行 | 終了コード 2、更新は始まらない | `test_cli_known_issue_pr93_f3_…`（Work の隔離版でのみ定義） |
| F-4 | 情報 | 本文を半分だけ送った接続が、サーバー側の読み取りタイムアウトが無く、クライアントが閉じるまでスレッドが残る（他の要求は妨げない。ローカルのみ） | Content-Length 100 で 1 バイトだけ送る | 読み取りタイムアウト | （再現のみ） |
| F-5 | 情報 | Origin ヘッダーの無い POST は受け付ける（ブラウザーの別サイトからは Origin が付くため拒否される）。同じ端末の非ブラウザープロセスは呼べる | `curl` 相当 | デモの保護範囲（ループバック・架空）の外として記録 | `test_known_issue_pr93_f5_…` |
| F-6 | 情報 | Referrer-Policy・`base-uri` が無い（強化の余地） | ヘッダー確認 | 任意 | — |

Sandbox 側の既知限界（数値を含む曖昧文が `clarity` で「できている」、`phase`／`format`／`certainty` の不正値が `validate` を通る）は Work の再現どおり**私の再現でも確認**した（Browser pane：「いろいろな活動を3回頑張りました。」→「答えの明確さ：できている」）。これは Claude 所有の契約・評価の欠陥で、別 PR で直す（Issue #75）。

## 独立に確認したこと（無変更の実行）

**A-1 パッチ・隔離**（`INDEPENDENTLY_VERIFIED` は Work のコードの再現に限る）
- 事前条件 4 ファイルの正規化 SHA は、(a) 配布版 `work-faq-v3`（CRLF）と (b) 現行の Work コード（LF、**読み取りのみ**）の**両方**で全件一致。
- 4 ファイルのどれかに実変更を加える → 4/4 で `Precondition mismatch`、出力は作られない。改行だけの差は受理。事前条件のファイルが欠けても何も作らない。
- 出力先：既存／入れ子（`..` 経由を含む）／コピー元と同じ／コピー元の親／既存ディレクトリへのジャンクション／ソース内を指すジャンクション配下 → すべて拒否。2 回目の実行は拒否され既存を上書きしない。コピー元のツリーは前後でバイト一致。DB ファイルは作られない。無関係な git リポジトリの中でも実際に適用される。パッチは二重適用できない。
- 隔離結果を Claude の #76 パッチ（SHA `4b9afba2…`、Work の記録と一致）の結果と照合：`store.py`・`generic.py`・`revisions.py` は**改行を正規化すると同一**。`revise_notices.py` だけが異なり、差は Work の `--reason-json` と `reason=` の受け渡しのみ（想定どおり）。
- 変更点の構造：承認（batch → approved）→ head 移動 → イベント → 理由、の順（INV-06）。

**A-2 トランザクション**（`tests/test_finalize_abnormal_paths.py`：Claude のパッチ版 42 件、Work の隔離版 56 件〔CLI 試験を含む〕）
- 書き込みの各段（記事・根拠 head・記事 head・イベント・理由）で例外を注入 → **全表の全行・スキーマ・`user_version`・整合性検査が前後で一致**、head は空のまま。head 移動の失敗は「先に approved にした」状態も巻き戻す。
- QA 入力 hash／記事 hash の不一致・欠落、QA 失敗（`rejected` になり head は動かず再承認不可）、二重 finalize（承認 1 回・理由 1 件）、失敗後の再試行（ちょうど 1 回成功）、rollback 済み、候補でない batch、存在しない batch、他の大学の根拠を引く記事、同じ head から作った 2 本目の batch（`concurrent head change`）、2 スレッドの同時 finalize（1 件だけ成功）。
- **アプリの異常終了**：別プロセスで `os._exit(9)`（head・イベント書込み後、commit 前）→ DB は前と同一、整合性 ok、再実行で 1 回承認。
- 接続条件：`store.connect` は `foreign_keys=ON`・`recursive_triggers=ON`・`sogh_write_ok` を設定、素の接続は `sogh_write_ok` が無い。登録範囲：コピーしたツリーの `sqlite3.connect` を全件確認し、能力を登録するのは `EvidenceStore.connect` と `promote_candidate` の書き込み接続のみ。他は監視・収集用の別 DB、読み取り専用、バックアップ先。
- 能力の無い接続は、`INSERT OR REPLACE`・`INSERT`（head）、`UPDATE update_batches`、`DELETE`／`UPDATE update_events`、`DELETE revision_reasons` のどれも拒否される。`DROP TRIGGER` はできるが DB-17 が失敗として検出する（既知の限界）。
- **`sogh_write_ok` は能力であり認証ではない。** 署名のない整合した QA で finalize でき DB-18 が通る（D2）ことは、Work の試験どおり残る。真正性の保証ではない。

**A-3 reason**：`{}`・`[]`・文字列・`0`・空／空白の理由・不正な `source_changed`／`reason_class`・`actor` 欠落・`source_changed` クラスと値の矛盾はすべて**全体を巻き戻す**。追加フィールド（`approved_by_user` など）は保存されず伝播しない。理由なし → 行なし（作り出さない）。旧スキーマに理由を渡すと全体拒否。CLI：フラグ無し → `None`、オブジェクトはそのまま転送、非オブジェクト 7 種は終了コード 2 で更新開始前に停止、壊れた JSON／BOM 付き／不正 UTF-8 は更新開始前に例外（Windows の PowerShell の `Out-File -Encoding utf8` は BOM を付ける点に注意）。例外：**`null`（F-3）**。

**A-4 `demo/`**（`tests/test_pr93_isolation_and_demo.py`：実サーバーを起動して 91 件、2 回実行して同結果。Browser pane でも実操作）
- Host／Origin：`localhost`・ポート無し・`0.0.0.0`・`evil.example`・サフィックス偽装・IPv6・Host 無し → 403。Origin が `null`・別サイト・別スキーム・末尾スラッシュ・`localhost` → 403（GET／POST とも）。別サイトの `text/plain` フォーム POST → 403。
- ヘッダー：全応答（404・403 を含む）に `no-store`・`nosniff`・CSP（`default-src 'self'`・`script-src 'self'`・`frame-ancestors 'none'`、`unsafe` 無し）。GET／POST 以外は 501。ソース・未登録パス（`..`・`%2e%2e`・`//`・`\`・クエリ付き）は 404。
- 本文：空・16 KiB 超・不正 JSON・配列・`null`・不正 UTF-8・深い入れ子・非数値の Content-Length → 400／413 の JSON、セッションは作られない。誤型の `case_id`・回答・経過時間・報告の各項目 → 400。**開いていない／古い turn への回答は 200 で `accepted:false`（保存されない）**。
- メール・電話番号は回答・終了応答のどこにも戻らない。同時 4 件の上限、reset で解放、30 分で失効。同意 3 種は独立・既定 false・保存／公開なし。ページは外部リソース・`localStorage`・`eval`・`innerHTML`・インラインスクリプトを使わない。
- Browser pane（実ブラウザー）：外部リソース要求 0（同一オリジンの 3 件のみ）、`localStorage`／`sessionStorage`／Cookie 0、コンソールエラー 0。ケース選択 → 条件確認 → 練習 → 追質問（回答の引用）→ フィードバック（限界の表示）→ 受験報告の流れを確認。
- サーバーの標準エラー：応答済みの切断の `ConnectionAbortedError` のみ。回答本文・要求本文は出ない（`log_message` 無効）。

## 実行していないこと（`NOT_RUN`・成功に数えない）
- Work の既存 247 試験（`SOGH_SOURCE_ROOT`・`SOGH_LEGACY_DB` など、手元に無い入力が必要）。
- この head での実コピー v06 の g4／追加型の再実行（Work の報告 22/22・20/20 は未確認。以前の head では私が同じ harness を使い捨てクローンで実行済み）。
- Work の Edge／Playwright 試験（`browser_smoke.py`）。私は Browser pane で代替した。
- 出力先が symbolic link の場合（この環境では権限が無い）。ジャンクションは確認。
- Linux での `prepare_isolation.py` の挙動（`tests/test_pr93_isolation_and_demo.py` は PR の統合後に CI の Linux／Windows で実行される）。
- 人が使いやすいと感じるか、評価の妥当性（`NOT_RUN`）。

## 再レビューの記録（head `2019231`、2026-11-02）
| 指摘 | 結果 | 独立に確認したこと |
|---|---|---|
| F-1 | **修正を確認** | Browser pane で選択肢が 6 件（`unknown／individual／group／presentation_then_qa／online／other`）、`individual` を選んで送信でき、外部要求・`localStorage`・コンソールエラーは無し。試験は HTML の構造（各 option が整形式で、値の集合が契約の `InterviewFormat` と一致、不正な終了タグが無い） |
| F-2a | **修正を確認（別の方式）** | 作りかけの出力は自動削除されないが、`.work-isolation-status.json` が `in_progress`→`failed`（失敗した手順を記録）／`completed`（パッチの SHA と書き出した 4 ファイルのハッシュ、実ファイルと一致）。失敗した出力への再実行は拒否。**マーカーが `completed` でなければ使わない**運用が必要（強制終了では `in_progress` のまま残る、と Work も明記） |
| F-2b | **修正を確認** | `core.autocrlf` が `true`／`false`／`input` のどれでも、4 ファイルの出力はバイト単位で同一（LF） |
| F-3 | **修正を確認** | `--reason-json` が `null` のファイルは終了コード 2、更新は始まらない（フラグ無しは従来どおり `None`、オブジェクトはそのまま転送） |
| 回帰 | 確認 | 修正後の head から作った新しい隔離コピーで、Work の試験 **31/31（無変更）**。私の試験は旧 `test_known_issue_*` を修正後の挙動の試験へ反転し、`finalize` の異常系 56 件（Work の隔離版）・42 件（Claude のパッチ版）、隔離とデモの 95 件が成功 |

未対応のまま残る：F-4（読み取りタイムアウト無し）・F-5（Origin 無しの POST）・F-6（Referrer-Policy・`base-uri`）。いずれも情報で、ループバック・架空データのデモの範囲。`NOT_RUN` は初回のまま（Work の既存 247 試験、この head での実コピー g4・追加型、symbolic link、Linux、人の使いやすさ）。

## 依頼（初回）
- **Work**：F-1 の修正（必須）、F-2a・F-2b・F-3 の修正（推奨）。修正後の head を知らせてください。私の試験の `test_known_issue_*` は修正で意図的に失敗するので、Claude 側で反転します（Work は私の試験を編集しない）。
- **Claude**：CI への Work 新規 20 件の接続（別 PR）、Sandbox の `clarity` と受験報告の不正 enum（別 PR・Issue #75）。
