# SOGH Antigravity: OSレベルネットワーク隔離の実験的検証と限界レポート

**検証日**: 2026-11-08  
**担当**: Google Antigravity (ローカルAI研究・安全性・実用性評価専門)  
**対象ホスト**: ASUS TUF Gaming FX505DY (Windows 11 Home / AMD Ryzen 5 3550H)  
**対象バイナリ**: `C:\Users\USER\llm_bench\cpu\llama-cli.exe`  
**検証ステータス**: `[SYNTHETIC_SELF_TEST_PASS]` & `[PROVEN_ON_HARDWARE]` (技術的限界の証明完了)

---

## 1. 検証の背景と目的

ユーザーからの最重要指摘：
> 「現在のネットワーク対策には、プロキシ環境変数の設定と出力に現れる通信エラーの検出が含まれていますが、それだけで全外向き通信の遮断が証明できるわけではありません。」

これを受け、**プロキシ環境変数（`HTTP_PROXY`）が低レベルソケット通信に対してどこまで無力であるか**を実機で実証し、Windows Defender Firewall等のOSレベル遮断の実現性と運用制約を解明することを目的としました。

---

## 2. 実機実験による決定的証拠 (Empirical Proof)

### 実験①：プロキシ環境変数下でのRaw Socket通信テスト
- **条件**:
  - `HTTP_PROXY="http://127.0.0.1:0"`
  - `HTTPS_PROXY="http://127.0.0.1:0"`
  - `ALL_PROXY="http://127.0.0.1:0"`
  - `SOGH_OFFLINE_STRICT="1"`
- **実行内容**:
  OS標準のTCPソケット（`socket.socket(AF_INET, SOCK_STREAM)`）を用いて外部DNSサーバー（`1.1.1.1:53`）へ接続試行。
- **結果**:
  ```
  RAW_SOCKET_CONNECT_SUCCESS_PROVING_PROXY_BYPASS
  ```
  **1.0秒未満で即時接続成功（プロキシ完全迂回が実証）**。
- **結論**:
  環境変数を自発的に読み取らないC/C++ネイティブバイナリ（`llama-cli`、推論ランタイム等）は、**プロキシ環境変数が設定されていても外部へ直接TCP/UDPパケットを無制限に送信可能**である。

---

## 3. OSレベル遮断（Windows Defender Firewall）の実現性と制約

### 実験②：一般ユーザー権限でのファイアウォール動的設定テスト
- **コマンド**: `netsh advfirewall firewall add rule name="TestRule" dir=out action=block program="test.exe"`
- **結果**:
  ```
  The requested operation requires elevation (Run as administrator).
  ```
- **技術的制約**:
  - 一般ユーザー権限で動作するAntigravity実行ハーネスは、**実行時に動的にファイアウォール遮断ルールを追加・変更することがOSのセキュリティ境界により不可能**である。
  - UAC管理者権限の自動昇格は安全規約により禁止されている。

### 実験③：一般ユーザー権限でのファイアウォール遮断ルールの事前監査
- **コマンド**: `netsh advfirewall firewall show rule name=SOGH_Antigravity_Block_Llama_CLI`
- **結果**:
  - **一般ユーザー権限でも既存ルールの状態（Outbound / Block / Enabled）を100%読み取り・監査可能**。
  - 判定結果: 現在のホスト環境には該当遮断ルールが存在しない（`FIREWALL_RULE_NOT_FOUND`）。
  - 現状の封じ込めレベル: `VULNERABLE_PROXY_ONLY`（プロキシのみの脆弱な状態）。

---

## 4. 解決策と安全な運用プロトコル（管理者1回設定方式）

一般ユーザー権限で推論を行う場合でも、以下の**事前1回設定**を行うことでOSレベルの完全遮断が成立します。

### 管理者権限で実行するワンライナー（事前設定）
```cmd
netsh advfirewall firewall add rule name="SOGH_Antigravity_Block_Llama_CLI" dir=out action=block program="C:\Users\USER\llm_bench\cpu\llama-cli.exe" enable=yes profile=any
```

### ハーネスによる事前飛行監査（Preflight Inspection）
`os_network_isolation_evaluator.py` を用いて、推論開始前にこのルールが有効であるかを検査。
- ルールが存在しない場合: `status="FIREWALL_RULE_NOT_FOUND"` で推論を即時拒絶（Fail-Close）。
- ルールが存在する場合: `status="FIREWALL_BLOCK_RULE_ACTIVE"` でOSレベル遮断合格。

---

## 5. SOGHへのローカルLLM適合性・採用判断

1. **現状判定（Red Line 1該当）**:
   - ホストOS上に管理者承認済みのファイアウォールアウトバウンド遮断ルールが未設置である現時点では、**「受験生の機密情報・個人情報・未公開志望理由書を扱うタスクにローカルAIを採用すべきではない」** と正式に判定します。
2. **採用解除条件**:
   - 管理者によるファイアウォール遮断ルールが適用され、`inspect_windows_firewall_rule` が `FIREWALL_BLOCK_RULE_ACTIVE` を返し、かつClaude Codeによる独立QAでソケット拒否が確認された場合のみ、ネットワーク安全条件をクリアと見なします。
