# SOGH Antigravity: ローカルAI安全統合契約仕様書 (v1.0.0)

**状態**: 設計・検証仕様固定 / 実モデル実行なし (HOLD_REAL_MODEL_RUN.txt 維持) / SELF_TEST済み  
**準拠方針**: SOGH04 STR-069、Issue #174、#199、#214、STR-007〜011、STR-068

---

## 1. 目的と担当境界

本書は、将来SOGHの公式DB検証や面接エンジンにローカルAI（オンデバイスLLM）を安全に接続する際の**入出力契約・リソース制約・拒絶ゲート**を定義します。

> [!IMPORTANT]
> - 本書は**将来の安全な接続のための仕様定義**であり、現時点で実際の統合や推論を開始するものではありません。
> - Claude Code（面接エンジン・受容プロトコル）や ChatGPT Work（本番DB・Web本体）と競合する重複実装は行いません。
> - 本書に基づくテストはすべて Antigravity による `SELF_TEST` であり、Claude Codeによる `独立QA` およびユーザーによる `正式受容` とは厳密に区別されます。

---

## 2. ハードウェア前提とリソース制約 (Preflight Gate)

ローカルAIを起動する前に、以下の4条件を100%満たす必要があります。1つでも違反した場合は `PREFLIGHT_*_FAIL` として起動を即時拒絶します。

| 検査項目 | 基準値 | 判定API / 手法 | 拒絶時ステータス |
|---|---|---|---|
| **物理空きRAM** | **>= 2,200 MB** | Win32 `GlobalMemoryStatusEx` | `PREFLIGHT_RAM_FAIL` |
| **AC電源接続** | **AC接続中 (100%)** | Win32 `GetSystemPowerStatus` | `PREFLIGHT_POWER_FAIL` |
| **CPUダイ温度** | **< 76.0 °C** | HWiNFO64 SM2 共有メモリ (`CPU (Tctl/Tdie)`)<br>※ACPI fallbackは明示許可時のみ | `PREFLIGHT_THERMAL_FAIL` |
| **ユーザーホールド** | **ファイル非存在** | `HOLD_REAL_MODEL_RUN.txt` の不在確認 | Exit Code 3 / `BLOCKED` |

---

## 3. オフライン隔離と既知の技術的限界 (Network Egress Containment & Known Limits)

SOGHにおける受験生データ・機密保持のため、実行ハーネスレベルでネットワーク通信の遮断・検知を試行します。**ただし、本機構は「完全な物理遮断」を証明したものではありません。**

1. **強制オフライン環境変数（合成試験成功）**:
   子プロセスの起動環境に `HTTP_PROXY="http://127.0.0.1:0"`, `HTTPS_PROXY="http://127.0.0.1:0"`, `ALL_PROXY="http://127.0.0.1:0"`, `SOGH_OFFLINE_STRICT="1"` を注入。
2. **通信例外検知と出力破棄（合成試験成功）**:
   子プロセスが出力ストリーム内でソケット通信や外部接続を試みた痕跡（`ProxyError`, `ConnectionRefused`, `127.0.0.1:0` 等）が検知された場合、直ちにプロセスを強制終了（kill）し、`status="NETWORK_EGRESS_DETECTED_FAILCLOSE"` で停止。全出力を `[REDACTED_DUE_TO_NETWORK_VIOLATION]` として破棄。
3. **⚠️ 既知の重大な技術的限界（未検証・実機未証明）**:
   - **Raw Socket接続の未遮断**: 環境変数を解釈しないC/C++ネイティブバイナリ（`llama-cli`等）が直接OSのソケットAPI（Winsock `connect()`）を呼んだ場合、本ハーネス単体ではパケット送出を遮断できません。
   - **DNS名前解決の漏洩リスク**: UDP port 53によるDNS問い合わせはプロキシ環境変数の適用外となる場合があり、ドメイン問い合わせログが外部に漏洩するリスクが残存します。
   - **サイレント通信の検知不能**: 出力ストリームに例外文字列を出さずに通信を完了させた場合、標準出力監視では検知できません。
   - **SOGH採用判断への影響**: OSレベルの完全隔離（Windows Defender Firewallでの該当プロセスの明示的アウトバウンド拒否ルール、またはAppContainer等の隔離サンドボックス）が独立QAによって検証されない限り、「機密・個人情報を扱うタスクにローカルAIを採用すべきではない」と判定します。

---

## 4. 入力契約 (Input Contract)

上位システムからローカルAIへプロンプトを渡す際の事前検証ルール：

- **文字数上限**: 最大 4,000 文字（超過時は `REJECTED_OVERSIZED_INPUT`）。
- **不可視文字除去**: ゼロ幅文字（`\u200B`等）、BOM（`\uFEFF`）、制御文字（`\x00`〜`\x1F`）を事前サニタイズ。
- **センシティブ語句除外**: 家庭環境、宗教、政治的信条、病歴、年収などの個人属性を自動除外。

---

## 5. 出力契約と拒絶ゲート (Output Contract)

ローカルAIから上位システムへ結果を返す際の検証ルール（`enforce_strict_output_contract`）：

| 出力状態 | 検知パターン | 上位システムへの返却値 | 隔離措置 |
|---|---|---|:---:|
| **完全一致** | `VERIFIED_MATCH` または 定型JSON | `verdict: "MATCH"` | なし |
| **矛盾検出** | `CONTRADICTION: <理由>` | `verdict: "CONTRADICTION"` | 隔離 |
| **根拠不足** | `UNVERIFIED: <欠落事実>` | `verdict: "UNVERIFIED"` | 隔離 |
| **禁止置換** | `PROHIBITED_SUBSTITUTION: <理由>` | `verdict: "PROHIBITED_SUBSTITUTION"` | 隔離 |
| **プロンプト漏洩** | 指示文・テンプレートのオウム返し | `verdict: "UNKNOWN_FORMAT_FAIL_CLOSE"` | **即時隔離** |
| **秘密・PII漏洩** | トークン、パスワード、メール、電話等 | `verdict: "UNKNOWN_FORMAT_FAIL_CLOSE"` | **即時マスク・隔離** |
| **制御コード汚染** | ANSIエスケープ、Nullバイト混入 | `verdict: "UNKNOWN_FORMAT_FAIL_CLOSE"` | **即時隔離** |
| **短文ノイズ** | 3文字未満の無意味な文字・記号 | `verdict: "UNKNOWN_FORMAT_FAIL_CLOSE"` | **即時隔離** |

---

## 6. 将来の統合に向けた独立QA要件

本仕様を将来SOGH本番機能へ統合する前に、以下の独立QA（Claude Code等による検証）が必須となります：

1. **ネットワーク遮断独立検証**: 意図的に外部API通信を試行するテストコードに対する独立プローブ（Failing Probe）。
2. **温度センサー完全途絶検証**: HWiNFO共有メモリおよびACPIの両方が途絶した際の完全フェイルクローズの独立検証。
3. **実機ダイ温度のキャリブレーション**: HWiNFO64起動状態での Ryzen 5 3550H の Tctl/Tdie 取得精度の実機確認。
