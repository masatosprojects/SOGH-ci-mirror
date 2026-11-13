# SOGH Antigravity: ハードウェア・レディネス & RAM 最適化運用ランブック (Runbook)

**文書対象**: ASUS TUF Gaming FX505DY (AMD Ryzen 5 3550H / RAM 8GB / Radeon RX 560X / Windows 11)  
**管轄領域**: `research/antigravity-local-ai/`  
**目的**: ローカルLLM (Qwen3-1.7B-Instruct-Q4_K_M.gguf) の実機推論安全実行に向けたハードウェア前提条件の解除手順およびメモリ最適化運用の規定。

---

## 1. フェイルクローズ (Fail-Close) 安全ゲートの前提条件

本リポジトリの `supervised_inference_runner.py` は、以下の **すべての前提条件が同時に満たされない限り、いかなる場合も実モデルプロセスを起動しません（Fail-Close）**。ユーザーからの直接承認があっても、安全回路が自律的に遮断します。

| チェック項目 | 判定基準 | 遮断時の挙動 / エラー符号 |
|---|---|---|
| **空き物理メモリ** | Available RAM $\ge$ 2,200.0 MB | `PREFLIGHT_RAM_FAIL: Available RAM (<current>) < 2200.0 MB` |
| **CPUダイ直接温度** | HWiNFO64 SM2 共有メモリ経由で Tctl/Tdie 取得、$\text{temp} < 76.0^\circ\text{C}$、かつデータ鮮度 10秒以内 | `PREFLIGHT_THERMAL_BLOCKED: Direct CPU die verification failed` |
| **給電状態** | AC電源接続 (`on_ac == True`) | `PREFLIGHT_POWER_FAIL: Battery operation prohibited` |
| **単一プロセス排他** | PIDトークンによるロック取得 | `PREFLIGHT_LOCK_FAIL: Another inference instance running` |
| **実行バイナリ/モデル** | SHA-256 / 完全パス一致のホワイトリスト | `PREFLIGHT_BINARY_FAIL` / `PREFLIGHT_MODEL_FAIL` |

---

## 2. 実機環境のボトルネックと現状診断

### 2.1 現状の制約
- **総物理メモリ**: 7.88 GB (8GB)
- **現状の空きメモリ**: 約 1,400 MB 〜 1,600 MB (ブラウザ・IDE・バックグラウンドプロセス稼働時)
- **必要空きメモリ**: 2,200 MB 以上 (Qwen3-1.7B-Q4_K_M モデルウェイト約 1.1 GB + コンテキスト 2048 / スクラッチバッファ約 0.6 GB + 安全マージン 0.5 GB)
- **温度センサー**: マザーボード ACPI ゾーン (`57.05 C`) は認識されているが、CPU Direct Die (Tctl/Tdie) を取得するための HWiNFO64 共有メモリが停止中。

---

## 3. 実機推論レディネス確立のための手順書 (ステップ・バイ・ステップ)

実モデル推論テストを安全に実行するには、以下の手順でホストマシンの状態を整備します。

### ステップ 1: HWiNFO64 の起動と「共有メモリサポート」の有効化
1. **HWiNFO64 を起動**:
   - スタートメニューから `HWiNFO64` を管理者権限で実行します。
2. **センサーのみモード (Sensors-only) で開始**:
   - 起動時のダイアログで「Sensors-only」にチェックを入れて「Start」をクリック。
3. **共有メモリの有効化 (Shared Memory Support)**:
   - センサーウィンドウ右下の歯車アイコン（Settings / Configure Sensors）をクリック。
   - 「General」タブを開き、**「Shared Memory Support」にチェックを入れる**。
   - （※無料版 HWiNFO の場合、共有メモリは1回につき12時間有効です。期限切れの警告が出たら「Re-enable」を押してください）
4. **確認**:
   - `python research/antigravity-local-ai/scripts/diagnostics.py` を実行し、`sensor_status: COMPONENT_TEMP_VERIFIED_GREEN` と表示されることを確認します。

### ステップ 2: 物理空きメモリの確保 (Available RAM $\ge$ 2,200 MB)
1. **重いアプリケーションの一時最小化・終了**:
   - 不要なブラウザのタブ（YouTube、重いWebアプリ等）を閉じる。
   - 他のバックグラウンド開発ツール（Docker、不要なElectronアプリ等）を終了する。
2. **空きメモリの確認**:
   - PowerShell にて以下を実行：
     ```powershell
     python -c "import psutil; free=psutil.virtual_memory().available/1024/1024; print(f'Available RAM: {free:.1f} MB (Required >= 2200.0 MB) -> {\"GREEN\" if free>=2200 else \"BLOCKED\"}')"
     ```
   - 出力が `GREEN` になれば、安全ゲートを通過可能となります。

### ステップ 3: 最小安全設定での推論テスト実行
安全ゲートが GREEN になった段階で、最も低負荷なパラメータで推論を実行します。

- **実行コマンド**:
  ```powershell
  python research/antigravity-local-ai/scripts/supervised_inference_runner.py --test-mode
  ```
- **パラメータ制約 (不変条件)**:
  - `threads`: 2 (Ryzen 5 3550H の 4コア中 2コアに制限)
  - `ctx_size`: 2048 (最大コンテキスト長)
  - `max_tokens`: 128 (出力トークン長上限)
  - `gpu_layers`: 0 (CPU推論、VRAM/共有RAM圧迫回避)
  - `temp_threshold`: 76.0℃ (76.0℃到達で即座に子プロセスSIGKILL)

---

## 4. トラブルシューティング

| 現象 | 原因 | 対処方法 |
|---|---|---|
| `PREFLIGHT_RAM_FAIL` | 空きRAMが 2200MB 未満 | ブラウザタブやバックグラウンドタスクを終了し、メモリを解放する。 |
| `PREFLIGHT_THERMAL_BLOCKED` | HWiNFO64 が起動していない、または共有メモリが無効 | HWiNFO64 の設定で "Shared Memory Support" を有効化する。 |
| `PREFLIGHT_POWER_FAIL` | ACアダプタが抜けてバッテリー駆動になっている | PCをAC電源に接続する。 |
| `PREFLIGHT_LOCK_FAIL` | 前回のクラッシュまたは別プロセスがロックを保持 | `research/antigravity-local-ai/.instance.lock` のPIDを確認し、正常終了している場合は手動で安全確認の上削除。 |
