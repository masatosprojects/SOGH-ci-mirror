# SOGH Antigravity — Phase 2B Session Handoff & Thermal Integration Report

**Session Date**: 2026-11-07 07:45 JST  
**Agent**: Google Antigravity (3rd Development Agent: Local AI & Resource Management)  
**Workspace**: `C:\Users\USER\Projects\SOGH-collab-antigravity`  
**Base Repository**: `masatosprojects/SOGH-collab`  
**Latest Master SHA**: `359ccec3bbe046716c8ba686ff5450af6f17d5ac` (incorporating STR-045)  
**Branch**: `antigravity/local-ai-scaffold`  
**Issue**: [#174](https://github.com/masatosprojects/SOGH-collab/issues/174)  
**Draft PR**: [#175](https://github.com/masatosprojects/SOGH-collab/pull/175)  

---

## 1. HWiNFO64の利用可能性確定（TASK 1）

- **実機調査結果**:
  - HWiNFO64 Portable版（Version 8.54）が **すでにローカル環境に存在** することを確認：
    - 実行ファイル: `C:\Users\USER\llm_bench\hwinfo\app\HWiNFO64.exe`
    - 設定ファイル: `C:\Users\USER\llm_bench\hwinfo\app\HWiNFO64.INI`（`SensorsOnly=1` 設定済み）
    - 配布アーカイブ: `C:\Users\USER\llm_bench\hwinfo\dl\hwi_854.zip`（2026/11/05 取得済み）
  - **稼働状態**: 現状はプロセス未起動。
  - **Shared Memory Support**: `HWiNFO64.INI` に未記載（デフォルト無効）。
  - **新規ダウンロード**: **完全不要（0バイト）**。
  - **追加費用**: **0円（個人利用無料）**。
  - **ライセンス上の留意点**: HWiNFO64無料版のShared Memory Supportは連続12時間で自動リセットされるため、長期間連続運用には向かない（単発推論検証には十分適合）。商用利用にはProライセンスが必要。
  - **ユーザー手動起動手順**:
    1. `C:\Users\USER\llm_bench\hwinfo\app\HWiNFO64.exe` を起動（Ring 0 ドライバ `HWiNFO64A.SYS` 読込のためUAC管理者昇格を承認）。
    2. Sensors画面の歯車アイコン（Settings）を開く。
    3. 「Shared Memory Support」にチェックを入れてOKを押す（または `HWiNFO64.INI` に `SharedMemorySupport=1` を追記して起動）。

---

## 2. 実CPU温度取得モジュールの実装（TASK 2 & 3）

新規モジュール: [`research/antigravity-local-ai/scripts/thermal_sensor_reader.py`](../scripts/thermal_sensor_reader.py)  
テストコード: [`research/antigravity-local-ai/tests/test_thermal_sensor_reader.py`](../tests/test_thermal_sensor_reader.py)

1. **ハードウェア識別とセンサー分離**:
   - AMD CPU内部ダイ温度（Tctl/Tdie）: `Global\HWiNFO_SENS_SM2` を `ctypes` による純粋なユーザーモード共有メモリマッピングで読み取り。識別子: `AMD_RYZEN_3550H_SMU_TCTL_TDIE`（`is_direct_die=True`）。
   - マザーボードACPIサーマルゾーン: Windows Performance Counter `\_tz.thrm`。識別子: `ACPI_MOTHERBOARD_THERMAL_ZONE`（`is_direct_die=False`）。
2. **鮮度・固着判定**:
   - `poll_time` が3.0秒以上経過した古いデータは即座に破棄（`None` 返却）。
   - タイムスタンプの逆行・停止を検知した場合は `UNKNOWN` へ移行。
3. **安全ラッパーとの動的接続**:
   - `SupervisedInferenceRunner.run_preflight_checks` において、固定メタデータではなく `ThermalSensorManager.evaluate_preflight_thermal_gate` を呼び出す構造へ全面改訂。
   - `COMPONENT_TEMP_VERIFIED_GREEN` でない限り、**実推論は必ず `PREFLIGHT_THERMAL_BLOCKED` として遮断（BLOCKED）**。

---

## 3. 監視準備時間の整合性確立（TASK 4）

- **実測値の特定**:
  - `read_acpi_temperature`（PowerShell実行）の所要時間を実測した結果、**`1.885秒`** を要することを確認。
  - 従来の準備待機時間 `timeout=2.0秒` は、わずかな負荷変動で `WATCHDOG_STARTUP_TIMEOUT` を誤発報する危険領域にあった。
- **改訂仕様**:
  - 準備フェーズの待機時間: **`MONITOR_STARTUP_WAIT_SEC = 6.0秒`** に緩和（初期測定の完了を確実に待機）。
  - 推論実行フェーズの30秒上限: 監視準備完了後に単調時計 `start_mono` を計測開始するため、**準備時間の遅延が30秒推論上限を圧迫しない完全分離** を確立。
  - 実行中のインジェスト時間監視: 2.0秒タイムアウトで迅速にフェイルクローズ。

---

## 4. RAMの現状とユーザー推奨操作（TASK 5）

- **実機測定値（2026-11-07 07:40 JST）**:
  - 物理RAM総量: 8,001.9 MB (7.81 GB)
  - 現在の空きRAM: **`1,446.8 MB` (1.41 GB)**（負荷率 81%）
  - 推論開始条件: **`2,200 MB` (2.2 GB)**（不足量: 約 753 MB）
  - ページングファイル: 10.5 GB（使用 385 MB、ピーク 752 MB）
- **メモリ消費上位プロセス（実測 Working Set）**:
  - `Memory Compression`: ~740 MB（OS標準機能・停止不可）
  - `chrome`: ~727 MB（ブラウザタブ複数）
  - `ChatGPT`: ~777 MB（デスクトップアプリ複数）
  - `Antigravity`: ~557 MB（開発環境IDE）
  - `language_server`: ~282 MB（Python言語サーバ）
- **ユーザー推奨操作**:
  - Chromeブラウザの不要タブとChatGPTデスクトップアプリを一時終了することで、約 **1.4 GB** の物理RAMが解放され、空きRAMは **~ 2.8 GB** まで回復して開始ゲートをクリア可能。
  - ※エージェントによるユーザーアプリやDefenderの自動終了は行いません。

---

## 5. 初回推論の具体的実行手順（TASK 6・待機用プロトコル）

推論実行許可が得られた際に使用する厳格な単発実行手順：

```powershell
# 1. 前提条件の充足確認（RAM >= 2.2GB、HWiNFO64 Shared Memory有効化）
cd C:\Users\USER\Projects\SOGH-collab-antigravity

# 2. 安全ラッパー経由の単発実行（有人監視下・CPU 2スレッド・GPUオフロードなし）
python -c "
import sys
sys.path.insert(0, 'research/antigravity-local-ai/scripts')
from supervised_inference_runner import SupervisedInferenceRunner, SafeInferenceConfig

runner = SupervisedInferenceRunner()
config = SafeInferenceConfig(
    prompt='【架空国立北都大学 2027年度 AC型総合選抜】募集人員は15名です。募集人員の数値を1行で回答してください。',
    threads=2,
    threads_batch=2,
    ctx_size=1024,
    predict_tokens=32,
    gpu_layers=0,
    temp=0.1
)
result = runner.execute_production_inference(config)
import json
print(json.dumps(result, indent=2, ensure_ascii=False))
"
```
**【遵守事項】今回は手順の策定までであり、ユーザー明示許可前の実推論実行は厳格に抑止しています。**

---

## 6. テスト実行実績（全46件 PASS）

```powershell
python -m unittest discover -s research/antigravity-local-ai/tests
Ran 46 tests in 18.261s - OK
```

| テストスイート | 件数 | 結果 |
|---|---|---|
| `test_mock_eval.py` | 23 | 全件 PASS |
| `test_supervised_inference.py` | 16 | 全件 PASS |
| `test_thermal_sensor_reader.py` | 7 | 全件 PASS |
| **総合計** | **46** | **全件 PASS（エラー・失敗ゼロ）** |

---

## 7. 実推論開始判定：【BLOCKED】

| 評価項目 | 現状値 | 基準 | 判定 |
|---|---|---|---|
| **CPUダイ直接温度** | 未検証（HWiNFO未起動） | HWiNFO SM2連携必須 | **UNVERIFIED (BLOCKED)** |
| **空き物理RAM** | 1,446.8 MB (1.41 GB) | $\ge 2,200\text{ MB}$ | **FAIL (BLOCKED)** |
| **ACPI温度** | 50.05 ℃ (`\_tz.thrm`) | $< 76.0\text{ ℃}$ | PASS (ACPI観測) |
| **AC電源供給** | 接続中 (100%) | 必須 | PASS |
| **引数バリデータ** | 固定コマンド生成 / 2スレッド / ngl 0 | 必須 | PASS |
| **メモリ上限・死活監視** | 512KB上限 / 6秒準備同期完備 | 必須 | PASS |
| **ユーザー明示承認** | 未受領 | 単発・有人監視 | **WAITING** |
