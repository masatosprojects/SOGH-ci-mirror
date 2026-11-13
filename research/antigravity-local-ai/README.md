# SOGH × Google Antigravity — Local AI & Operations Foundation

**Workspace**: `C:\Users\USER\Projects\SOGH-Antigravity`  
**Agent**: Google Antigravity (3rd Development Agent of SOGH)  
**Role**: ゲーミングPC（ASUS TUF Gaming FX505DY）におけるローカルLLM基盤、資源監視、イベント駆動型非同期情報処理プロトタイプの設計・実装・検証  
**Base Repository**: `masatosprojects/SOGH-collab` (Private GitHub)  
**Governing Branch**: `antigravity/local-ai-scaffold` (PR #175)  

---

## 1. 事業の全体像と本拠地 (SOGH Product Vision & 5 Layers)

SOGHは単なるnote botやLLMのベンチマーク比較プロジェクトではありません。  
事業の全体像は、現在提案・調整中である [strategy/PRODUCT_VISION_AND_CHANNELS.md](../../strategy/PRODUCT_VISION_AND_CHANNELS.md)（PR #176）および承認済み決定台帳（`strategy/DECISIONS.md`）に基づき、以下の5層構造として整理されます。

```
[ 受験生・保護者・高校教員 ]
           │
           │ (note / SNS による認知・外部情報発信・集客)
           ▼
╔═════════════════════════════════════════════════════════════════════════════╗
║          【 1. 本拠地：独自ドメイン上の自社Webプラットフォーム 】           ║
║                                                                             ║
║  ① 検証済み公式入試DBの直接提供 (大学別・学部別・学類別・方式別・年度別)   ║
║  ② 大学別AI模擬面接 (筑波大学AC入試等を先行、公式DBに基づく質問・追質問)   ║
║  ③ 公式情報の再検証依頼受付・匿名追跡 (未確認・古い・欠落情報の受付)        ║
║  ④ 将来的な受験経験共有・安全な交流コミュニティ                             ║
╚═════════════════════════════════════════════════════════════════════════════╝
           ▲                                       ▲
           │ (3. 公式情報DB: 共通基盤)              │ (独立QA・根拠検証)
[ ChatGPT Work: SOGH本体・本番DB ]    [ Claude Code: 独立QA・根拠検証 ]
           ▲
           │ (候補JSONの提案 / 疎結合)
[ 5. Google Antigravity: ゲーミングPC (本リポジトリ担当) ]
  - 大学公式サイト・要項差分のイベント駆動監視モック (Phase 1.7)
  - 資源・熱監視 (Win32 API) & フェイルクローズ停止機構
  - 安全なオフライン評価基盤 (外部送信ゼロ・個人情報ゼロ)
```

1. **独自ドメインの自社Web**: SOGHの主要な情報提供・サービス提供拠点。大学公式DBの閲覧、AI模擬面接、再検証依頼を一体として提供。
2. **note・SNS**: 主に集客、認知拡大、読み物記事の外部発信媒体。自社Web公式DBの代替公開先ではない。
3. **公式情報DB**: 内部の共通情報基盤。原典の版管理、候補抽出、根拠照合、受容済み公式情報の供給。
4. **AI模擬面接**: SOGHの中心的受験支援機能（初期実証: 筑波大学AC入試）。
5. **ローカルLLM基盤（Antigravity）**: 必要に応じて稼働する補助AI基盤。情報や公開の最終承認者ではなく、非同期の候補抽出・品質評価・資源監視を担当。

---

## 2. 3者の協業と非干渉境界 (Tri-Agent Responsibility Boundary)

| 担当 | 主管領域 | Antigravityの遵守ルール |
|---|---|---|
| **ChatGPT Work** | SOGH本体、DB・ワーカー、モデルルーター、模擬面接コア実装 | `OneDrive\ドキュメント\ChatGPT\SOGH`、本番DB、既存Task Scheduler、WorkのPRを変更しない |
| **Claude Code** | GitHub上の独立QA、根拠検証、記事QA、既存PR | Claude担当PRを上書きしない。自己試験を「独立QA合格」と偽装しない |
| **Google Antigravity** | ゲーミングPCのローカルLLM基盤、資源監視、イベント駆動モック、評価再現 | 既存正式DB・他AI領域を触らず、専用ディレクトリ `research/antigravity-local-ai/`、専用ブランチ、Draft PR #175 のみで活動 |

---

## 3. ディレクトリ構成 (Directory Structure)

```
research/antigravity-local-ai/
├── README.md                 # 本ドキュメント（ビジョン5層構造・全体方針）
├── AGENTS.md                 # エージェント行動規範・非干渉ルール
├── PROPOSED_VISION_ALIGNMENT.md # 自社Web構想と既存文書の不整合整理提案
├── .gitignore                # GGUF・キャッシュ・大容量ログ・資格情報の除外
├── docs/                     # 詳細設計書・再開ガイド
│   ├── ARCHITECTURE.md       # イベント駆動・安全停止アーキテクチャ
│   └── SETUP_AND_RESUME.md   # セッション再開・環境復帰手順
├── inventory/                # 読み取り専用で取得したPC・モデル資産情報
│   ├── model_inventory.json  # 物理確認された既存GGUFモデル一覧（5件）
│   └── hardware_inventory.json # ハードウェア構成と制約事項
├── scripts/                  # 診断・イベント監視・テスト実行スクリプト
│   ├── diagnostics.py        # Win32 API実RAM測定・推論プロセス検知・合成温度停止
│   ├── mock_event_monitor.py # 入力検証・動的差分抽出・同一性・衝突隔離・根拠検証
│   └── run_tests.py          # 18件の総合テストランナー
├── fixtures/synthetic/       # 外部送信・個人情報ゼロの架空テストデータ
│   ├── tsukuba_ac_mock_cases.json # 筑波AC向け架空面接・書類ケース
│   ├── mock_site_diff.json   # 予約済みテストドメイン（admission.example.com）差分
│   └── mock_official_db.json # 根拠検証用架空公式DBフィクスチャ
├── tests/                    # 自動評価・スキーマ検証テスト
│   └── test_mock_eval.py     # 18件の単体・境界・異常系・安全停止・ミューテーションテスト
└── handoff/                  # 他AI（Work/Claude）との情報共有
    ├── HANDOFF_TEMPLATE.md   # 引き継ぎ標準フォーマット
    └── SESSION_HANDOFF_PHASE1.md # Phase 1.7詳細引き継ぎレポート
```
