# SOGH Antigravity: GitHub Issue #199 正式進捗・安全検証報告（方針調整版）

**提出日**: 2026-11-08  
**報告担当**: Google Antigravity (ローカルAI研究・安全性・実用性評価専門)  
**対象コミットSHA**: `159234a` (origin/master)  
**関連Issue/PR**: #174, #199, #214 / PR #251, #252, #253, #254, #255 / STR-069

---

## 1. 担当境界と研究方針の厳守確認

1. **M1データベース開発の完全排除**:
   - 大学受験情報DBのデータ収集・保存・移行、面接エンジンの重複実装、製品Web開発は一切担当しません（ChatGPT WorkおよびClaude Code専任）。
2. **研究使命の再定義**:
   - Antigravityの使命は「将来のSOGHでローカルAIを使うべきかを、信頼できる技術的証拠によって判断可能にすること」です。
   - 品質や安全性が不十分である場合、**「ローカルLLMを採用しない」という結論も正当な成果**として取り扱います。
3. **実モデル停止（HOLD）の維持**:
   - `HOLD_REAL_MODEL_RUN.txt` を厳格に維持。実モデル推論・高負荷ベンチマークは一切実行していません（**NOT_RUN**）。
   - HWiNFOによる実ダイ温度、空きRAM（2,200MB）等の安全条件の緩和は行いません。

---

## 2. 安全機構の4段階検証マトリクス

検証レベルを以下の4段階に厳密に分類し、合成試験の成功を「実機検証済み」「完成」と混同しないよう是正しました。
- `[IMPLEMENTED]` : 実装済み
- `[SYNTHETIC_SELF_TEST_PASS]` : 合成・モック試験合格
- `[INDEPENDENT_QA_PASS]` : 独立QA合格
- `[PROVEN_ON_HARDWARE]` : 実機・実OS検証済み

| 検証項目 | 対象コード | 検証レベル | 独立QA | 判定・現状 |
|---|---|---|---|---|
| **実モデル停止ファイル遵守** | `standalone_production_runner.py` | `[INDEPENDENT_QA_PASS]`<br>`[PROVEN_ON_HARDWARE]` | あり (Claude済) | **実機証明完了** (exit code 3) |
| **物理RAM不足時安全停止** | `supervised_inference_runner.py` | `[SYNTHETIC_SELF_TEST_PASS]`<br>`[PROVEN_ON_HARDWARE]` | あり (仕様適合) | **実機証明完了** (Win32 API取得, 2200MB閾値) |
| **ACPI/ダイ温度の厳格区別** | `thermal_sensor_reader.py` | `[INDEPENDENT_QA_PASS]`<br>`[PROVEN_ON_HARDWARE]` | あり (Claude F-S1..S3) | **実機証明完了** (ACPI正直分類) |
| **センサー停止・停滞検知** | `thermal_sensor_reader.py` | `[SYNTHETIC_SELF_TEST_PASS]` | なし (要第三者QA) | **合成確認済** (タイムスタンプ静止停止) |
| **飛行中熱暴走・センサー喪失** | `supervised_inference_runner.py` | `[SYNTHETIC_SELF_TEST_PASS]` | なし (要第三者QA) | **合成確認済** (90℃超過時SIGKILL) |
| **クラッシュ復旧・孤立ロック保護** | `supervised_inference_runner.py`<br>`diagnostics.py` | `[SYNTHETIC_SELF_TEST_PASS]` | なし (要第三者QA) | **合成確認済** (生存保護・孤立検出) |
| **不正・破損出力の隔離** | `grounding_response_parser.py` | `[SYNTHETIC_SELF_TEST_PASS]` | なし (要第三者QA) | **合成確認済** (プロンプト漏洩・ANSI隔離) |
| **E2Eイベント駆動連携** | `mock_event_monitor.py` | `[SYNTHETIC_SELF_TEST_PASS]` | なし (要第三者QA) | **合成確認済** (staging候補生成・検疫) |
| **意図しない外部通信の拒絶** | `supervised_inference_runner.py` | `[SYNTHETIC_SELF_TEST_PASS]`<br>⚠️ **技術的限界あり** | なし (要第三者QA) | **未完成・限界あり**<br>※環境変数/エラー捕捉のみ。OSレベルのRawソケット/DNS遮断は未検証。 |
| **OSネットワーク隔離評価・監査** | `os_network_isolation_evaluator.py` | `[SYNTHETIC_SELF_TEST_PASS]`<br>`[PROVEN_ON_HARDWARE]` | なし (要第三者QA) | **実機証明完了**<br>※プロキシ迂回を実験証明。一般ユーザー権限での動的FW追加不可と事前監査を実証。 |
| **実モデル推論 (Qwen3-1.7B)** | `llm_bench/cpu/llama-cli.exe` | — | 未実施 (ホールド遵守) | **NOT_RUN** |

**テストスイート総計**: **105 / 105 PASS (100%)**、Failures: 0, Errors: 0

---

## 3. 最重要課題：ネットワーク遮断の限界と採用判断基準

現在のプロキシ環境変数注入および標準出力エラー文字列検知は、**「全外向き通信の遮断を証明するものではない」** ことを明確に報告します。
- C/C++バイナリがOSソケット（Winsock）を直接叩いた場合や、UDP port 53によるDNS問い合わせは遮断できません。
- 出力にエラーを出さずサイレントに外部通信を行った場合も検知不能です。
- **SOGH採用判断への示唆**: OSレベルのパケットフィルタ（Windows Defender Firewall API等）やサンドボックスによる遮断が第三者検証されない限り、個人情報・受験生機密を伴うタスクへのローカルLLM採用は推奨しません。

---

## 4. Claude Code 独立QAへの引き継ぎ（固定HEAD: `159234a`）

以下の検証証拠を整理し、Claude Codeによる独立QAを要請します：
1. **センサー停滞（Frozen Polling）の検証**: HWiNFO共有メモリシミュレータによるタイムスタンプ静止時の停止動作。
2. **孤立ロック（Stale Lock）の安全監査**: 急死プロセスによるロックが生存プロセスを保護しつつ誤消去されないことの検証。
3. **外部通信遮断の限界確認**: プロキシ環境変数適用下でのRawソケット通信試行による外部到達性の客観的評価。
