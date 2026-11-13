# SOGH Antigravity — Phase 2A.3 ローカルLLM実推論プロトコル

- **作成担当**: Google Antigravity（第3開発担当：ローカルAI・資源管理）
- **対象環境**: ASUS TUF Gaming FX505DY（AMD Ryzen 5 3550H / RX 560X 4GB / RAM 8GB / Win11）
- **対象モデル**: `C:\Users\USER\llm_bench\models\Qwen3-1.7B-Q4_K_M.gguf`（サイズ: 1.11 GB）
- **エンジン**: `C:\Users\USER\llm_bench\cpu\llama-cli.exe`（CPUバックエンド / 最大2スレッド / GPUオフロード厳禁）
- **監視ラッパー**: [`scripts/supervised_inference_runner.py`](../scripts/supervised_inference_runner.py)
- **評価用データ**: [`fixtures/eval/sogh_admission_eval_set_v1.json`](../fixtures/eval/sogh_admission_eval_set_v1.json) (v2.0 完全架空データ・構文検証済み)
- **更新日**: 2026-11-07 (Phase 2A.3 残課題解消・起動競合・インジェスト制限・CPU温度調査完了版)

---

## 1. CPU温度監視の優先調査結果と現状

### A. ACPIサーマルゾーン（実測値）とCPUダイ温度の本質的差異
- **現在取得中のセンサー**:
  - Windows Performance Counter: `\Thermal Zone Information(*)\High Precision Temperature (\_tz.thrm)`
  - 実測温度: **`50.05 ℃`**
  - 計測対象: マザーボード上のACPIサーマルゾーン（APUソケット周辺基板）
  - 特性: 熱容量の大きいPCB経由の温度伝導を観測するため、更新間隔は1〜2秒程度で安定。推論負荷時の瞬時なCPUダイ（シリコン微小部）のスパイク（秒未満で10〜20℃急上昇する現象）を直接捉えることはできません。
- **Ryzen 5 3550H（Picasso / Zen+）CPUダイ温度（Tctl/Tdie）の仕様**:
  - AMD SMU（System Management Unit）メールボックスレジスタ／PCI Configuration Space経由で取得される内部ダイ温度。
  - Windowsの通常ユーザーモードAPI（WMIや標準パフォーマンスカウンタ）には標準露出されておらず、**Ring 0（カーネルモード特権ドライバ）** を介してのみ直接読み取り可能です。

### B. 既存ツール・WMI・低負荷調査の結果
1. **標準WMI（`root\wmi:MSAcpi_ThermalZoneTemperature`, `root\cimv2:Win32_TemperatureProbe`）**:
   - 調査結果: インスタンスが存在せず（空応答）、ユーザーモードでの直接取得不可。
2. **ASUS独自WMI（`root\wmi:AsusAtkWmi_WMNB`）**:
   - 調査結果: WMIクラスは存在するものの、BIOSレベルのATK raw制御バッファ（DEVS/DSTSメソッド）呼び出しを要し、非公開パラメータを伴うため安全な読み取り手段としては不適。
3. **HWiNFO64（共有メモリ `Global\HWiNFO_SENS_SM2`）**:
   - 調査結果: プロセス未稼働、共有メモリ非存在。
   - **導入・利用可能性**:
     - HWiNFO64 Portable版（無料 / 個人利用無料）を起動し、「Sensors」画面の設定で「Shared Memory Support」を有効化すれば、カーネルドライバ（`HWiNFO64A.SYS`）経由で `Global\HWiNFO_SENS_SM2` に CPU Tctl/Tdie が直接公開され、Pythonから低負荷（数マイクロ秒）で直読可能となります。
     - 費用: **0円（完全無料）**。
     - 制約: 無料版では共有メモリ機能が12時間で自動リセットされるため、定期的な「再有効化」操作が必要（商用Pro版は無期限）。

### C. ステータス判定
- **ステータス**: **`THERMAL_ZONE_OBSERVED_COMPONENT_TEMP_UNVERIFIED`**（厳格維持）
- **方針**: CPUコアダイ温度の直接観測が未確立である以上、ステータスを勝手にGREENに変更せず、**実モデルの推論起動は引き続き厳格にBLOCK**します。

---

## 2. 物理RAM使用状況とプロセス分析

実機調査（2026-11-07 07:22 JST）：
- **物理RAM総量**: 8,001.9 MB (7.81 GB)
- **現在の空きRAM**: **~ 1,647 MB (1.61 GB)**（負荷率 79%）
- **開始ゲート閾値**: **`2,200 MB` (2.2 GB)**（不足量: 約 553 MB）
- **ページングファイル（`C:\pagefile.sys`）**: 割り当て 10,752 MB、現在使用 385 MB、ピーク使用 752 MB（健全に稼働中）

### メモリ消費上位プロセス（Working Set実測）
| プロセス名 | PID | メモリ消費量 | 備考 |
|---|---|---|---|
| **Memory Compression** | 3396 | 788.1 MB | Windows OSメモリ圧縮機能 |
| **chrome** | 複数 | ~ 740 MB | ユーザーブラウザタブ |
| **ChatGPT** | 複数 | ~ 695 MB | デスクトップアプリ |
| **Antigravity** | 複数 | ~ 565 MB | 開発環境・IDE |
| **language_server** | 14480 | 263.7 MB | Python言語サーバ |
| **MsMpEng** | 5016 | 195.5 MB | Windows Defender |

### ユーザー推奨操作（空きRAM 2.2GB 確保に向けて）
- ユーザー様が推論実行前に **Chromeブラウザの不要タブ** および **ChatGPTデスクトップアプリ** を一時終了するだけで、**約 1,400 MB** の物理RAMが即座に解放され、空きRAMは **~ 3,000 MB（3.0 GB）** まで回復します。
- **規約遵守**: エージェントによるユーザーアプリや他AIプロセスの自動終了は一切行いません。

---

## 3. Phase 2A.3 におけるスーパーバイザーの残課題解消

ファイル: [`scripts/supervised_inference_runner.py`](../scripts/supervised_inference_runner.py)  
テストコード: [`tests/test_supervised_inference.py`](../tests/test_supervised_inference.py)

### A. 監視スレッドの起動競合解消（Issue 1）
- **問題**: 以前は監視スレッド起動直後に子プロセスを生成していたため、監視スレッドが起動直後に異常終了した場合、子プロセスが監視なしで起動する危険があった。
- **改修**:
  - 2相同期イベント `monitor_ready_event` を導入。
  - 監視スレッドが起動し、初期のRAM・温度測定をパスして生存を確認するまで、メインスレッドは `subprocess.Popen` を保留。
  - 監視スレッドの起動失敗時は、**子プロセスを1回も生成せずに即座に起動中止**（`WATCHDOG_STARTUP_ABORT`）。
  - 子プロセス実行中は、メインスレッドが50ms周期で監視スレッドの生存（`is_alive()`）を監視。監視スレッドがクラッシュした場合は即座に子プロセスを強制終了（`WATCHDOG_DIED_PREMATURELY`）。

### B. インジェスト時点での出力メモリ上限強制（Issue 2）
- **問題**: 従来の `communicate()` は全出力を一旦メモリに吸い上げてから512KBに切り詰めていたため、子プロセスが無限出力ループに陥った際にメモリ枯渇を防止できなかった。
- **改修**:
  - `BoundedStreamReader` クラスを実装。
  - バックグラウンドで4KB単位のストリーミング読み取りを行い、`buffer`（bytearray）の上限を厳格に **512 KB** に制限。
  - 512KBを超えたデータは**メモリに保持せず即座に破棄（drain）** し、パイプのバッファ詰まりによる子プロセスデッドロックを防止。
  - 上限到達時は `limit_exceeded = True` を立て、メインループが検知して直ちに子プロセスを安全停止（`OUTPUT_LIMIT_EXCEEDED`）。

### C. 30秒実行上限の統一単調時計強制（Issue 3）
- 監視側と実行側で同一の単調時計締切（`deadline_mono = start_mono + effective_timeout`）を共有。
- 30秒を超えるパラメータが渡されても、内部で最大30.0秒に強制クランプ。
- 締切到達時は即座に `_terminate_child()`（polite terminate → force kill）を実行し、ゾンビプロセス残存ゼロを保証。

### D. 排他ロックの追加競合検証（Issue 4）
- 外部プロセスプローブによる排他ロック競合の遮断確認。
- 解放直後の別インスタンスによる再取得確認。
- ロックファイル内容の外部改ざん（所有者トークン書き換え）検知と誤削除防止の検証。

---

## 4. 単体・フォールトインジェクション試験結果（全39件 PASS）

```powershell
# 1. スーパーバイザー安全性・フォールトインジェクション試験 (16件 PASS)
python research/antigravity-local-ai/tests/test_supervised_inference.py -v
Ran 16 tests in 13.535s - OK

# 2. イベントモック・ライフサイクル・完全架空データ試験 (23件 PASS)
python research/antigravity-local-ai/tests/test_mock_eval.py
Ran 23 tests in 0.280s - OK
```

| テストスイート | 実行件数 | PASS | FAIL | SKIP | NOT_RUN |
|---|---|---|---|---|---|
| `test_supervised_inference.py` | 16 | 16 | 0 | 0 | 0 |
| `test_mock_eval.py` | 23 | 23 | 0 | 0 | 0 |
| **総合計** | **39** | **39** | **0** | **0** | **0** |

---

## 5. 初回実推論への移行条件と総合判定：【BLOCKED】

### 必須停止条件チェックリスト
1. [ ] **CPU温度の信頼できる監視の確立**: 未確立（ACPI観測値 50℃のみ、CPUダイ未確認）
2. [ ] **空きRAMが開始条件（$\ge 2,200\text{ MB}$）を満たす**: 未達（現在 ~1,647 MB）
3. [x] **監視スレッド故障時の停止が検証済み**: 検証完了（起動前失敗・実行中クラッシュ共に子プロセス起動抑止／即時停止）
4. [x] **実際のメモリ出力上限が実装済み**: 実装完了（`BoundedStreamReader` 512KB上限）
5. [x] **30秒の推論時間上限が検証済み**: 検証完了（統一単調時計締切）
6. [x] **排他ロックが安全**: 検証完了（トークン照合、他プロセス遮断、改ざん防止）
7. [x] **実モデルのコマンドと対象ファイルが確認済み**: 確認完了（Qwen3-1.7B, llama-cli.exe 存在確認済み）
8. [ ] **ユーザーがPCの前で監視できる**: 待機中
9. [ ] **ユーザーが単発推論を明示的に許可する**: 待機中

### 総合判定
**`BLOCKED`（実モデル推論の実行抑止を厳格維持）**

### ユーザー側で実行前に必要な最小限の操作
1. **空きRAM確保**: ブラウザ（Chrome）の不要タブ、ChatGPTデスクトップアプリを終了する（空きRAM 2.2GB以上へ）。
2. **CPUダイ温度方針の決定**:
   - 案A: HWiNFO64（無料ポータブル版）を起動し、Sensors設定で「Shared Memory Support」をONにする。
   - 案B: ACPIサーマルゾーン監視（50℃、マザーボード側）のみであることを理解・承諾の上で、CPU 2スレッド限定・短時間の単発推論を明示的に許可する。
3. **明示的な単発実行指示**: PC監視下での初回実行指示をエージェントに伝える。
