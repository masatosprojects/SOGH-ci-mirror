# Claude PR95レビューへの対応（2026-11-02）

対象：PR93旧head `cb03ff8`。独立レビュー文書はClaude PR95 head `e0533b6`。
判定CHANGES_REQUESTEDを受領。WorkからClaudeの判定を代行してPASSへ変えない。

追記：修正head `2019231`をClaudeが無改変で再実行し、`PASS_WITH_WARNINGS`と判定（PR93 comment6571886258）。F1/F2a/F2b/F3は確認済み。PR98の試験反転とPR97の報告契約修正を含むmaster `2694ec8`を競合なしで取り込み、最新版QAで統合を検証する。
PR97で報告契約の不正enum/boolean/数値型検査が追加された。旧 `sandbox-limit-observations.json` は修正前の観測で、現在も不正enumが通るという意味ではない。API形状は保たれ、Work側入力境界は引き続き使用する。

| 指摘 | 修正 | Workの再現・検証 |
|---|---|---|
| F1 必須 | 個人形式optionの開始タグを修正 | 実際の旧GitHub本文で再現。新規HTML構造テスト、実Edgeで全6option・individual選択・送信まで検査 |
| F2a 推奨 | `.work-isolation-status.json`を作成 | in_progress→completed/failed。コピー途中/patch検査失敗でfailed、元source不変、同じ出力の再使用は拒否 |
| F2b 推奨 | git apply/checkへ`-c core.autocrlf=false` | 外部設定true/false/inputの3通りでも更新ファイルのLF bytesが同じ |
| F3 推奨 | フラグ明示時はnullも非objectとして拒否 | null/false/0/[]が終了code2、run未呼出。フラグなしNone・objectの従来動作は既存試験で維持 |

WorkがF1を前回の画面試験で見落としていた。選択肢の存在を確認せずにフォーム送信だけで確認したためで、今回テストを追加した。
新規11件＋既存Work専用20件＝**31成功/失敗0/skip0**。全部合成。旧247件を加算しない。
現在のWorkルートから修正後パッチを適用した新しい隔離コピーで実行し、既存3DBモジュールは変更せず、callerのnull拒否だけを変更した。
実Edgeの2シナリオ成功、JavaScriptエラー0/外部要求0。人の使いやすさや評価品質はNOT_RUN。

失敗出力を自動削除しない。状態markerがcompleted以外なら使用しない。強制終了時はin_progressのままになることがある。
ディスク満杯でmarker自体を書けない場合や、原本/外部ファイルを書き換える攻撃を防ぐ機構ではない。
CLIの不正JSON/BOM/不正UTF8は更新前に失敗する従来挙動を維持し、今回BOM対応などへ拡張していない。

F4（不完全HTTP要求のread timeoutなし）、F5（Originなしの同じ端末の非ブラウザクライアント）、F6（Referrer-Policy/base-uri）は今回変更していない。
本デモはloopback/架空データ限定で、本番公開にそのまま転用しない。

Claudeの`test_known_issue_*`は今回の修正で意図的に失敗する。Workはその試験を編集せず、Claudeに正例/負例の反転と再レビューを依頼する。
Workの新規11件のCI接続もClaudeの担当。旧20件のCI接続PRと混同しない。
原本/監査DB/運用Workルート/worker/鍵/課金/noteへの変更なし。M1 2/8 NOT ACCEPTED維持。
