# SOGH Antigravity Architecture — Event-Driven Local AI Subsystem (v0.4.0)

## 1. システム全体像 (High-Level Architecture)

SOGHにおけるゲーミングPC（Antigravity: ASUS TUF Gaming FX505DY / AMD Ryzen 5 3550H / 8GB RAM）の役割は、常時高負荷推論を行うノードではなく、**「監視・イベント発生時のみ起動する非同期・疎結合の安全な推論・評価拠点」**です。

```
[ 大学公式サイト / 募集要項 ]
           │ (HTTP HEAD / 定期差分検知)
           ▼
[ Pythonイベント監視プロセス (軽量・常時) ]
           │
           │ 差分・再検証依頼が発生した場合のみ
           ▼
[ 厳格プロセス監視・安全関所 (supervised_inference_runner.py) ]
  ├── 起動前物理RAMチェック: >= 2,200 MB (2.2 GB)
  ├── AC電源接続確認 (バッテリー駆動時の過負荷防止)
  ├── 熱監視ゲート: < 76.0 °C (HWiNFO64 CPUダイ または 認可ACPI)
  └── 単一インスタンスロック (UUIDトークンによる同時実行遮断)
           │
           │ 安全基準通過時のみオンデマンド起動 (CPU 2スレッド制限)
           ▼
[ ローカルLLM 推論ノード (llama-cli.exe / Qwen3-1.7B-Q4_K_M) ]
           │
           │ 生成テキスト (バナー除去・有効回答検証済み)
           ▼
[ 決定的グラウンディング検証エンジン (evaluate_grounding.py) ]
  ├── 公式ドメイン検証 (https://www.tsukuba.ac.jp/)
  ├── 共通テスト必須化等の禁止選考要素注入検知 (PROHIBITED_SUBSTITUTION)
  ├── 過年度日程等の矛盾検知 (CONTRADICTION)
  └── SHA-256 原文ハッシュ完全一致検証 (MATCH)
           │
           │ 幻覚・未検証出力は直ちに検疫隔離 (quarantined=True)
           ▼
[ 候補ステージングキュー (staging_queue/) / Handoff レポート ]
           │
           ▼
[ 人間管理者 & Claude Code 独立QA による受容 ]
           │
           ▼
[ ChatGPT Work による本番DB・模擬面接システムへの反映 ]
```

---

## 2. 厳格な安全・フェイルクローズ原則 (Fail-Closed Invariants)

1. **二重安全熱監視 (Dual Thermal Safety Gate)**:
   - **通常本番モード**: HWiNFO64 共有メモリ（SM2）による直接 CPU ダイ温度（Tctl/Tdie）の検証済み GREEN（< 76.0 °C）を必須とし、センサー未接続時は直ちに起動拒否（`FAILCLOSE`）。
   - **ユーザー認可ACPIフォールバックモード**: ユーザーが明示的に実機動作を認可した場合のみ、マザーボードACPI温度（`\_tz.thrm`）による追跡を許可。ただし、センサー種別は偽装せず正直に `sensor_type="ACPI_THERMAL_ZONE"`, `is_direct_die=False`, `mode="USER_AUTHORIZED_ACPI_FALLBACK"` と証跡記録。
   - **実行中 0.1s 周期ウォッチドッグ**: 推論中であっても温度が 76.0 °C に達した瞬間、またはセンサー応答が途絶えた瞬間に子プロセスを強制終了（SIGKILL）。

2. **物理RAMフロア (Physical RAM Floor)**:
   - 起動前フリー物理RAMが **2,200 MB (2.2 GB)** 未満の場合はプロセスを起動しない。
   - 実行中フリー物理RAMが **700 MB** 未満に急減した場合は即座に推論を遮断。

3. **回答生成の厳格検証 (Authentic Generation Verification)**:
   - `llama-cli.exe` の起動バナーや対話プロンプト（`/exit`, `/regen` 等）のみが出力された場合、推論成功（SUCCESS）とは認めず、`EMPTY_OR_BANNER_ONLY_OUTPUT` として安全に失敗判定。
   - プロンプトに対する意味のある日本語回答テキスト（5文字以上）が抽出・検証された場合のみ結果受容。

4. **ユーザー緊急停止ホールド (User-Directed Real-Model Hold)**:
   - `HOLD_REAL_MODEL_RUN.txt` が `research/antigravity-local-ai/` に存在する場合、すべての実モデル推論エントリポイント（Pythonスクリプトおよびバッチファイル）は、いかなるプロセスも起動せず直ちに終了コード 3 で停止。
   - このホールドファイルはユーザー本人による明示的な判断によってのみ解除可能（AIによる自律削除は禁止）。

5. **本番DBおよび外部アクセスの完全分離**:
   - Antigravity は ChatGPT Work が管理する SQLite 本番 DB への書き込み権限を一切持たない。
   - すべての検証結果は `handoff/` および `staging_queue/` 内の JSON / Markdown レポートに出力。
