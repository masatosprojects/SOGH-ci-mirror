# SOGH Antigravity — Startup, Resume & Tri-Agent Coordination Protocol (v0.6.0)

**Governing Repository**: `masatosprojects/SOGH-collab` (Private GitHub)  
**Dedicated Local Path**: `C:\Users\USER\Projects\SOGH-collab-antigravity`  
**Dedicated Git Tree**: `research/antigravity-local-ai/` on branch `master`  
**Latest Tag**: `v0.6.0` (E2E Event Grounding Pipeline & Core Vision Axis Audit)  
**Issues & Coordination**: [#174](https://github.com/masatosprojects/SOGH-collab/issues/174) (Local AI), [#199](https://github.com/masatosprojects/SOGH-collab/issues/199) (Coordination Hub)

---

## 1. セッション開始・再開プロトコル (Startup & Resume Protocol)

毎回のセッション開始時および再開時には、必ず以下の手順を実行します：

1. **最新 master SHA の取得と記録**:
   - `git fetch origin master` を実行し、最新のコミットSHAを取得・記録します。
2. **ハードウェア & 安全総合診断のワンショット実行**:
   - `python research/antigravity-local-ai/scripts/diagnostics.py` を実行します。
   - 物理RAM（>= 2,200 MB）、AC電源、ハイブリッド熱センサー（HWiNFO SM2 / ACPI、< 76.0 °C）、ユーザーホールド状態（`HOLD_REAL_MODEL_RUN.txt`）を瞬時に確認します。
3. **自己単体テストスイートの全件実行**:
   - `python research/antigravity-local-ai/scripts/run_tests.py` を実行し、**92 / 92 PASS（100% 合格）** を確認します。
4. **ユーザーホールドテストの実行**:
   - `python -c "import tests.test_real_model_hold as m; m.test_the_hold_file_exists_and_explains_who_may_lift_it(); m.test_the_python_entry_points_stop_with_exit_code_3_and_start_nothing(); m.test_the_batch_launcher_checks_the_hold_before_anything_else(); m.test_the_batch_launcher_checks_the_real_hold_file_path_and_has_no_control_characters(); print('All 4 hold tests passed!')"` を実行し、実モデル停止ガードの正常性を確認します。
5. **正本資料の確認**:
   - `docs/AXIS_ALIGNMENT_AND_VISION_VERIFICATION.md`（初期軸との整合性確認書）
   - `handoff/SESSION_HANDOFF_PHASE2B_FINAL.md`（最新引き継ぎ書）
   - `strategy/DECISIONS.md`（採用済み事業判断、最新STR番号）

---

## 2. SOGHの事業ビジョンと各AIの担当（不変原則）

```
[ 受験生・保護者・高校教員 ]
           │
           │ (note / SNS による認知・外部情報発信・集客導線)
           ▼
╔═════════════════════════════════════════════════════════════════════════════╗
║                   【 SOGH 本拠地：自社Webプラットフォーム 】                ║
║                                                                             ║
║  ① 検証済み大学公式DBの直接提供 (大学別・学部別・学類別・方式別・年度別)   ║
║  ② 大学別AI模擬面接 (筑波大学AC入試等を先行、公式DBに基づく質問・追質問)   ║
║  ③ 情報の再検証依頼 (未確認・古い・欠落情報の受付と匿名追跡)                ║
║  ④ 受験経験共有・安全な交流コミュニティ (将来構想)                          ║
╚═════════════════════════════════════════════════════════════════════════════╝
           ▲                                       ▲
           │ (公式情報DB: 共通基盤)                │ (契約・独立QA)
[ ChatGPT Work: 本体実装・本番DB ]        [ Claude Code: 契約と独立QA ]
  - SOGH本体コード（src/）                 - DB整合性・根拠検証・記事QA
  - 公式情報DB（SQLite）・面接実装         - 契約レビュー・独立回帰テスト
           ▲
           │ (候補JSON提案 / 疎結合)
[ Google Antigravity: 専用領域でのローカル実験 ]
  - ゲーミングPC上のローカルLLM基盤・資源監視（Win32 API）
  - 公式要項差分のイベント駆動監視・E2E候補抽出（staging_queueへの提案）
  - 安全なオフライン評価基盤（本番DB不干渉・外部送信ゼロ・個人情報ゼロ）
```

- **SOGHの本拠地**: 所有する独自ドメイン上の自社Webプラットフォーム。
- **note・SNS**: 外部の情報発信および自社Webへの送客・集客媒体。
- **ChatGPT Work**: SOGH本体の実装と本番DB接続を担当。
- **Claude Code**: 契約と独立QAを担当。
- **Google Antigravity**: 専用領域（`research/antigravity-local-ai/`）でのローカル実験・資源管理・モックを担当。

---

## 3. 引き継ぎと同期プロトコル (Handoff & Sync Protocol)

1. **記録の原則**:
   - 確認した `master` SHA、担当範囲、認識の差、未確認事項を必ずIssue #199 等に記録します。
2. **三者の受け渡し手順**:
   - 他のAI（WorkまたはClaude）へ作業を受け渡す際は、相手の次回セッション指示文に該当Issue/PRのリンクを添えます。
   - **相手が確認したSHAを返信したことをもって同期を確認します。**
3. **承認の厳格な分離**:
   - **事業方針の採用**（`strategy/DECISIONS.md` への追加）
   - **技術の受け入れ**（Claude Code による独立QA・契約受容）
   - **本番操作の承認**（本番DB書き込み・公開・追加課金・実モデルホールド解除等）
   - これら3つの承認は完全に別個として扱い、1つの承認をもって他方を代行・省略しません。
