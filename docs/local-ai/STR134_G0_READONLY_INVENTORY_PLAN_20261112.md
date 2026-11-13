# STR-134 段階 G0：読取専用 既存決定・環境棚卸し計画書（提案）

- **文書ID**: `SOGH-PLAN-STR134-G0-20261112`
- **作成日**: 2026-11-12
- **タスクID**: `A-21`（STR-134 G0 棚卸し計画書の策定）
- **作成担当（Author）**: Google Antigravity（Gemini 4 Argon / Gemini 3.8 Flash, ゲーミングPC）
- **独立QA担当（Independent QA）**: Claude Code（メインPC）
- **位置づけ**: **AI_PROPOSAL / PLAN_ONLY / NOT_EXECUTED**
  - 本文書は計画の提案であり、実環境の棚卸し実行、実モデルの起動、機器操作、外部通信、DB変更、課金の許可を含みません。

---

## 1. 目的と背景

STR-134（ローカルLLM・大学公式DB自律運営構想 Q1〜Q34）は、Pi とゲーミングPCの二本柱による段階的な自律運営ロードマップ（G0〜G7）を定めています。
本計画書は、その最初の入口である **「段階 G0：読取専用の既存決定・環境の棚卸し」** を安全に実施するための対象、参照資料、期待される証拠、停止条件、および NO_GO ゲートを定義するものです。

**基本原則**:
1. **完全読取専用（Read-only）**: 実機・OS・設定・DB・Git リポジトリへの書き込み・変更は一切行わない。
2. **実モデル推論の凍結維持（STR-097 HOLD）**: いかなるローカル LLM ランタイムも起動・ロードしない。
3. **職務分掌と作者分離**: Antigravity が計画し、Claude Code が独立 QA を行い、本人が実行の GO/NO-GO を判定する。

---

## 2. 棚卸しの対象範囲（Target Scope）

棚卸しを実行する場合の対象は以下の 4 領域に限定する：

1. **既存決定・規約台帳（Governance & Decisions）**:
   - `strategy/DECISIONS.md`（STR-001〜STR-137）
   - 本人の設計意図ログ（Q1〜Q34）と master への反映状況
   - `AGENTS.md` および `docs/COORDINATION.md` の役割境界
2. **ハードウェア・実行環境スペック（Hardware & OS Environment）**:
   - **ゲーミング PC（ASUS TUF FX505DY）**: CPU、内蔵GPU/dGPU、実搭載RAM（8GB）、ストレージ空き容量、Windows 11 OS バージョン、Python ランタイム。
   - **Raspberry Pi 4B**: Broadcom BCM2711 4コア、RAM 3.8GB、64GB microSD 使用状況、Raspberry Pi OS 64-bit Desktop、SSH（鍵認証のみ）、ポート開放状況（22 のみ、rpcbind 停止済み）。
   - **メイン PC**: 非連続稼働の前提、現行の単一正本ライター権限保持状態。
3. **安全・監視センサー環境（Thermal & Safety Telemetry）**:
   - ゲーミング PC の温度取得手段（HWiNFO / WMI / OpenHardwareMonitor / AMD ADL 等の安全読取可能性）。
   - 温度センサーの「固定値・偽装値（Fake/Mock）」と「物理ダイ実測値」の識別検証可能性（※Q34 課題 P3）。
4. **データベース・スキーマ整合性状態（Database & Contract State）**:
   - 凍結移行連鎖（0001〜0014）の適用状況。
   - `fact_keys.json`（v1.7.1）登録簿および追記専用トリガーの健全性。

---

## 3. 参照する原本資料（Authoritative Documents to Consult）

| 資料名 | 格納場所 | 棚卸しで確認する要件 |
|---|---|---|
| `AGENTS.md` | リポジトリ直下 | 各エージェント（本人、Claude Code、Antigravity、Work）の不可侵境界 |
| `strategy/DECISIONS.md` | `strategy/` | STR-095（保全）、STR-096（非認定）、STR-097（HOLD/G02）、STR-111（関門）、STR-134（Q1〜Q34）、STR-135（事業検証） |
| `HOLD_REAL_MODEL_RUN.txt` | リポジトリ直下 | 実モデル推論の完全凍結（STR-097）の遵守確認 |
| `docs/THREE_DEVICE_ARCHITECTURE_20261108.md` | `docs/` | 3端末の役割分担、非対称性、メインPC非連続稼働 |
| `docs/raspberry-pi/PI_BUILD_LOG_20261112.md` | `docs/raspberry-pi/` | Pi 4B の G0〜G2 構築記録、SSH 鍵認証、ハードニング状態 |
| `docs/DB_COMPLETION_DASHBOARD.md` | `docs/` | M1 ゲート（8関門）の進捗（現在 2/8 受容）と残課題 |
| `strategy/LOCAL_LLM_DB_OPERATIONS_VISION_STR134_20261112.md` | `strategy/` | 採用された最終像 Q1〜Q34 の全条項 |

---

## 4. 期待する証拠（Expected Evidence to Collect）

G0 棚卸しが実行された場合に収集すべき客観的証拠（エビデンス）：

1. **決定の無矛盾性証明書（Decisions Consistency Matrix）**:
   - STR-001〜137 と Q1〜Q34 の間に衝突（矛盾）がないことを示す突合表。
   - 特に「LLM は公式事実の最終認定者でない（STR-096）」と「自律反映（Q18）」の優先順位関係（非LLM先行・人間/独立QAフォールバック）の明文化。
2. **ハードウェア環境の実測スペック台帳（Hardware Inventory Sheet）**:
   - 各端末の OS、CPU、実効利用可能 RAM、ストレージ空き容量の実測スナップショット。
   - Pi 4B の `ss -tlnH`（リッスンポートが 22 のみであることの証跡）。
3. **温度・安全テレメトリの健全性評価（Telemetry Assessment）**:
   - ゲーミング PC において、OS 標準または安全な読取手段で取得できる温度指標の特定。
   - 温度センサーが固定ダミー値を返却していないことの判定証跡（変動確認）。
4. **ネットワーク境界・秘密情報非漏洩の監査ログ（Security & Credentials Audit）**:
   - ルーターで WAN 向けポート開放が一切行われていないことの確認。
   - Git リポジトリおよびログファイル内に SSH 秘密鍵、トークン、パスワード、実受験生個人情報（PII）が存在しないことの正規表現走査結果。

---

## 5. 停止条件および NO_GO ゲート（Stopping Conditions & NO_GO Criteria）

棚卸しの計画および将来の実行において、以下のいずれかに該当した場合は**直ちに作業を停止（ABORT / NO_GO）**し、人間へエスカレーションする：

| # | NO_GO 条件 | 理由・規約根拠 | 処置 |
|:---:|---|---|---|
| **NG-1** | 実モデルの起動・ロード・推論試行 | STR-097 違反、G02 違反 | 即時プロセス停止、HOLD 状態を再確認 |
| **NG-2** | 温度センサーの真正性が未確認（偽値・固定値の疑い） | STR-134 Q34 課題 P3 | G3 実モデル比較への移行を不可とし、保留 |
| **NG-3** | 外部ネットワークへの新規巡回・通信の試行 | STR-097、事業規約違反 | ネットワーク通信遮断、人間報告 |
| **NG-4** | 正本 DB への直接書き込みまたは Work 所有コードの改変 | 権限境界違反、M1 契約違反 | 操作破棄、使い捨て環境破棄 |
| **NG-5** | 追加課金（3万円超過）または有料 API の呼び出し | STR-126、STR-135 D2 違反 | 実行禁止、課金ゼロの維持 |
| **NG-6** | Pi またはゲーミング PC での WAN ポート開放要求 | ネットワーク分離（Q31）違反 | 要求拒否、LAN 限定を維持 |
| **NG-7** | 未観測・欠測状態を「正常（NORMAL/PASS）」と偽る表示 | 状態契約（Q14, Q30）違反 | `UNKNOWN` / `UNRESOLVED` を強制 |

---

## 6. 次段階（G1: M1正式受容、G2: 非モデル型評価）への接続条件

本 G0 計画書が承認された後、将来の段階へ進むための前提条件：
1. **G0 棚卸し実行の完了と独立 QA（Claude Code）の PASS 判定**:
   - 証拠台帳が揃い、NO_GO 条件に抵触しないことが第三者確認されること。
2. **G1（M1 の正式受容）の完了（最優先）**:
   - Work 復帰後の残ゲート検証を経て、本人の署名により M1 が正式受容されること（S1 到達）。
3. **G2（非モデル型評価部品）への着手**:
   - A-02 で検証済みの E01〜E03 設計に基づき、完全架空データのみで非モデル型部品（原典SHA照合、年度/方式scope検査、公式遵守台帳）を構築すること。
4. **本人の個別 GO 承認**:
   - 各段階への移行は本人の明示的な個別指示を必須とし、自動昇格は行わない。
