# 納品物のマニフェスト監査と、実行で生まれる成果物（bytecode）：全体回帰の 2 失敗の再整理と契約案

**ラベル：契約案・独立再現（`SELF_VALIDATED`／Claude）。** テストの削除・skip・マニフェストの対象の無断除外は**していない**。監査（`src/integration/audit_handoff.py::check_manifest`）は変更していない。M1 は 2/8、NOT ACCEPTED。

## 1. Work の報告した 2 失敗（全体 2202 pass・2 fail・0 skip）の分解
| 失敗 | 原因 | 独立の確認 |
|---|---|---|
| ① 旧 `known_issue` の P-3 試験（`tests/test_pr109_read_contract_review.py`） | Claude 所有の旧試験が、P-3 修正前の脆弱な動作を期待値にしていた。Work の修正（Cf 文字の拒否）が正しいので期待が誤り | **解消済み**：同じ攻撃入力を拒否する回帰試験へ反転（旧 head で 135 件失敗・新 head で 0 件）。`claude/pr109-p3-regression`（統合後は master） |
| ② 納品物のマニフェスト監査（`test_independent_audit_of_each_handoff_…`） | Work 側の実行が、納品物のディレクトリの中に `__pycache__`（bytecode）を作った。監査は「納品物の全ファイルがマニフェストに載る」ことを検査するので、載っていない `.pyc` で失敗する。ハッシュを記録して別の場所に退避すると、同じ監査が pass した | **決定的に再現した**（下記） |

## 2. ②の再現（`research/inbox/work-updates-v2` の納品物、master＋Work の最新 head の統合コピー）
1. 何も import していない状態：`check_manifest` ＝ **pass**。
2. 通常の Python（bytecode 有効）で、納品物の `admissions_pipeline` を import：納品物の中に `.pyc` が **3 個**でき、`check_manifest` ＝ **fail**（`files not in manifest: …__pycache__/…cpython-312.pyc`）。
3. 生成された `__pycache__` を除く：**pass**。
4. `python -B`（bytecode 無し）で同じ import：**pass**（何も作られない）。
→ 失敗の原因は、納品物の内容ではなく**実行の仕方**（bytecode を納品物の中へ書く設定）。`pytest tests/` はテスト側が `sys.dont_write_bytecode = True` を設定するので影響を受けず、`scripts/local_ci.py` も `PYTHONDONTWRITEBYTECODE=1` で実行する。リポジトリ全体（Work のディレクトリも含む）を 1 回で走らせる実行は、Work の試験が納品物のパッケージを bytecode 有効で import すると、同じ実行の中の監査が落ちる。

## 3. 監査の境界（確認したこと）
| 観点 | 事実 |
|---|---|
| 作成対象の境界 | 監査は、納品物のルートの下の**ファイルシステム上のすべてのファイル**（`rglob`）を、マニフェストの一覧と照合する。Git が追跡しているかどうかは見ない |
| Git の追跡／未追跡 | `__pycache__` は Git に入らない（無視設定）が、監査は**未追跡のファイルも対象**にする（エディタの一時ファイルも同様に失敗する）。チェックアウトのクリーンさが前提 |
| `__pycache__`・bytecode | ファイル名に Python の版が入る（`cpython-312`／`cpython-311`）ので、**版の違う実行はそれぞれ別のファイルを作る**。納品物の中に書かれると、マニフェストは版ごとに無数の組み合わせを持つことになり、記録は不可能 |
| OS 依存の出力 | 行末（CRLF／LF）でテキストのハッシュが変わる（監査の注記：`core.autocrlf=false` のチェックアウトで検査）。パスの区切りは `/` に正規化して照合 |
| 実行前後の差 | 監査は、実行の**前**の状態を基準にする方式ではなく、実行後の状態を検査する。したがって、実行が納品物へ書いたものはすべて失敗として見える（これは意図した性質） |
| 空の出力先 | 納品物が空・マニフェストが無い場合は検査の対象外ではなく失敗（マニフェストが必要） |
| 正規化ルール | パスは `/` に統一、SHA-256 と任意のバイト数。ほかの正規化（改行・Unicode）はしない |

## 4. 契約案（仕様上の変更。**実装は合意後**）
1. **実行規約（採用を推奨、変更はテスト実行側のみ）**：納品物のパッケージを import する実行は、`PYTHONDONTWRITEBYTECODE=1`、`-B`、または **`PYTHONPYCACHEPREFIX=<納品物の外>`**（bytecode を別の場所へ出す。Python 3.8 以降）のいずれかを必ず設定する。`scripts/local_ci.py` は設定済み。GitHub Actions のワークフローへの追加（`env: PYTHONDONTWRITEBYTECODE: "1"`）は、ワークフローの変更なのでユーザーの承諾が要る（無料。CI が動く間のみ有効）。
2. **監査の厳しさは維持**：派生物を黙って除外しない。`__pycache__` を無視する案は、納品物へ**実行可能な内容**を紛れ込ませる経路を作りうるので採らない（無視するなら「対応する `.py` がマニフェストに載り、`.pyc` はそのソースから再生成できる」場合に限り、件数と一覧を報告に出す、という条件つきの案を別に議論）。
3. **失敗の名前を分ける（診断の改善のみ）**：未記載のファイルのうち `__pycache__/*.pyc` は、失敗の理由として `bytecode_in_delivery` と明示し、原因（実行規約の違反）が分かるようにする。**判定（fail）は変えない**。
4. **試験の位置づけ**：Work の PR の試験（`research/inbox/work-*`）と納品物（`work-updates-v2` ほか）の関係を文書化し、Work の全体実行の手順に「納品物の外へ bytecode を出す」設定を加える（Work の所有）。

## 5. 未実行
**GitHub Actions の CI は起動せず結果なし**。Linux・macOS での挙動（`.pyc` の名前・パス区切り）は未確認（Windows・Python 3.12／3.11.9 のみ）。
