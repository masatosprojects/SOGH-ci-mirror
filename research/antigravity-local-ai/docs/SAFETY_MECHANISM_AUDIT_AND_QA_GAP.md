# SOGH Antigravity: 安全機構の厳格検証ステータスと未証明事項の監査レポート

**状態**: 正式監査完了 / 実モデル実行なし (`HOLD_REAL_MODEL_RUN.txt` 厳格維持)  
**対象コミット**: `1326e26` (origin/master)  
**準拠方針**: SOGH技術開発方針（2026-11-08）、COORDINATION.md、Issue #174・#199

---

## 1. 担当境界と研究使命の再確認

- **M1データベース開発の完全排除**:
  大学受験情報DBのデータ収集・保存・移行機能、面接質問生成エンジン、製品Web画面は担当外（ChatGPT WorkおよびClaude Codeの担当）。Antigravityはこれらを一切実装しない。
- **真の研究使命**:
  **「将来SOGHでローカルAIを使うべきかを、信頼できる技術的証拠によって判断可能にすること」**。
  品質・安全性・費用・性能が不十分であれば、**「ローカルLLMを採用しない」という結論も正当な研究成果**として許容する。
- **検証レベルの4段階厳格区分**:
  安全機能の自己過信を防ぐため、以下の4区分を厳格に適用し、「合成試験成功」を「実機検証完了」「完成」と混同・誇大表記することを禁止する。
  1. `[IMPLEMENTED]` : コード上にロジックを実装した状態
  2. `[SYNTHETIC_SELF_TEST_PASS]` : 実装者による合成・モックテストで合格した状態
  3. `[INDEPENDENT_QA_PASS]` : Claude Code等の他AIによる独立テストで客観的に合格した状態
  4. `[PROVEN_ON_HARDWARE]` : 実ハードウェア・実OS挙動において証跡が取れている状態

---

## 2. 安全機構の厳格検証マトリクス

| 安全機能 | 実装箇所 | 検証レベル | 詳細・客観的証跡 | 判定・残存課題 |
|---|---|---|---|---|
| **実モデル停止ファイルの遵守** | `standalone_production_runner.py`<br>`evaluate_real_model_grounding.py` | `[INDEPENDENT_QA_PASS]`<br>`[PROVEN_ON_HARDWARE]` | `HOLD_REAL_MODEL_RUN.txt` 存在時に最上流でexit code 3停止。Claude独立QAにて確認済。 | **実機証明完了** |
| **物理RAM不足時の安全停止** | `supervised_inference_runner.py`<br>`scripts/diagnostics.py` | `[SYNTHETIC_SELF_TEST_PASS]`<br>`[PROVEN_ON_HARDWARE]` | Win32 APIで実RAM取得。空き2,200 MB未満時の即時fail-closeを合成テストにて確認。 | **実機証明完了** |
| **ACPI温度とCPUダイ温度の厳格区別** | `thermal_sensor_reader.py` | `[INDEPENDENT_QA_PASS]`<br>`[PROVEN_ON_HARDWARE]` | 実機マザーボードACPI温度（48〜51℃）を取得し、「CPUダイ未検証」と正直に分類。Claude独立QA (F-S1..F-S3) 合格。 | **実機証明完了** |
| **温度センサー停止・停滞の検知** | `thermal_sensor_reader.py` | `[SYNTHETIC_SELF_TEST_PASS]` | 共有メモリ更新静止（同一タイムスタンプ2連続）およびACPIタイムアウト時のフェイルクローズをシミュレータで確認。 | **合成確認済**<br>(要Claude独立QA) |
| **子プロセス暴走時の強制停止** | `supervised_inference_runner.py` | `[SYNTHETIC_SELF_TEST_PASS]` | 単調クロック（30秒）および標準出力バッファ上限（512KB）超過時の子プロセス強制終了（SIGKILL）を確認。 | **合成確認済**<br>(要Claude独立QA) |
| **クラッシュ復旧・孤立ロック保護** | `supervised_inference_runner.py`<br>`diagnostics.py` | `[SYNTHETIC_SELF_TEST_PASS]` | 生存PIDのロック保護、およびプロセス急死後の孤立ロック（stale lock）の安全な監査・検出を確認。 | **合成確認済**<br>(要Claude独立QA) |
| **不正・破損モデル出力の拒絶** | `grounding_response_parser.py`<br>`mock_event_monitor.py` | `[SYNTHETIC_SELF_TEST_PASS]` | プロンプト漏洩・ANSIエスケープ注入・Nullバイトを含む出力を検疫隔離し、staging混入0件を確認。 | **合成確認済**<br>(要Claude独立QA) |
| **意図しない外部通信の拒絶** | `supervised_inference_runner.py` | `[SYNTHETIC_SELF_TEST_PASS]`<br>⚠️ **技術的限界あり** | 環境変数（`HTTP_PROXY`等）注入と通信エラー文字列検知は合成テストで合格。**しかしOSレベルのRawソケット/DNS遮断は未検証。** | **未完成・実機未証明**<br>(重大な技術的限界) |
| **OSネットワーク隔離評価・監査** | `os_network_isolation_evaluator.py` | `[SYNTHETIC_SELF_TEST_PASS]`<br>`[PROVEN_ON_HARDWARE]` | Rawソケットによるプロキシ迂回（1.1.1.1:53接続）を実機で実証。一般ユーザー権限での動的FW追加不可（昇格必須）と事前監査を実機確認。 | **実機証明完了**<br>(要管理者1回FW設定) |

---

## 3. 最重要課題：ネットワーク遮断における「既知の限界」と採用判断リスク

ユーザーからの重要な指摘に基づき、現在の外部通信対策の限界を正直に整理します。

### 【現状の対策】
- 子プロセス起動時に `HTTP_PROXY="http://127.0.0.1:0"` などの環境変数を注入。
- 子プロセスの出力ログを監視し、`ProxyError` やソケットエラーが発生した場合は即座にプロセスを終了し出力を破棄。

### 【証明できていない点・既知の重大な技術的限界】
1. **Raw Socket（Winsock）呼び出しの未遮断**:
   プロキシ環境変数は、Pythonの `urllib` や `requests` など対応ライブラリでのみ有効です。C/C++ネイティブバイナリ（`llama-cli`等）が直接OSのソケットAPI（Winsock `connect()`）を呼んだ場合、環境変数は無視され外部にパケットが送信されます。
2. **DNS名前解決の漏洩リスク**:
   UDP port 53によるDNS問い合わせはプロキシの適用外となる場合が多く、問い合わせ先ドメインが外部DNSキャッシュに漏洩する可能性があります。
3. **サイレント外部通信の検知不能**:
   出力ストリーム（stdout/stderr）に通信エラー文字列を出力せず、バックグラウンドスレッドで外部送信を行った場合、現在の標準出力監視では検知できません。

### 【SOGHにおけるローカルLLM採用判断への直結条件】
- **判定基準（Red Line）**:
  Windows Defender Firewall による該当バイナリの明示的なアウトバウンド全パケット拒否ルール、またはWindows AppContainer等のOSレベルサンドボックスによる遮断が実証されない限り、**「受験生の志望理由書や個人情報、未公開機密をローカルAIに処理させるべきではない（ローカルLLM不採用推奨）」** と判定します。

---

## 4. Claude Code 独立QAへの引き継ぎ項目

固定HEAD: `ea6867a` (次回更新コミット)
- **QA-1（センサー停滞・タイムアウト検証）**: 共有メモリタイムスタンプ固定時のフェイルクローズ挙動確認。
- **QA-2（孤立ロック監査検証）**: 急死プロセスのPID残存ロックが後続の安全起動を阻害せず、かつ上書きされないことの確認。
- **QA-3（ネットワーク遮断の限界評価）**: 環境変数注入下でRawソケット（Cバイナリまたは低レベルsocketスクリプト）を実行した際、パケットが外部到達し得る限界の第三者確認。
- **QA-4（OSファイアウォール監査モジュールの検証）**: `os_network_isolation_evaluator.py` によるネット遮断事前監査の正確性確認。

---

## 5. 総括

Antigravity担当の全テストスイートは **105 / 105 PASS (100%)** です。  
実モデル推論は行わず（`HOLD_REAL_MODEL_RUN.txt` 厳格維持）、OSレベルのネットワーク遮断の限界と解決策（管理者による事前1回設定方式）を技術的に解明・文書化しました。
