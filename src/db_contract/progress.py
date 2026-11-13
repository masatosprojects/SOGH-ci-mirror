"""Development progress board, generated from ONE data file (docs/development_progress.json).

    python -m src.db_contract.progress [--write | --check]

It writes docs/DEVELOPMENT_MASTER_PLAN.md, docs/DEVELOPMENT_PROGRESS.md and docs/DB_COMPLETION_DASHBOARD.md.

How progress is counted — and what is NOT counted:
* A process's progress = acceptance criteria that are `verified` WITH evidence / all its criteria. Nothing else: not the number of tests,
  not the number of merged PRs, not "the code exists". A criterion that is unverified, not run, or only checked on synthetic data adds nothing.
* A DB area's completeness = the dimensions that are `yes` with evidence / 7. `partial` is shown but is not counted. `real_data` can only
  be `yes` when its evidence names a real database (copied_real_db / production_read_only).
* `accepted` and `operational` are different states; `operational` is allowed only from P9 on.
* M1 is reported complete only when EVERY gate is verified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs" / "development_progress.json"
OUTPUTS = {"plan": REPO / "docs" / "DEVELOPMENT_MASTER_PLAN.md", "progress": REPO / "docs" / "DEVELOPMENT_PROGRESS.md",
           "dashboard": REPO / "docs" / "DB_COMPLETION_DASHBOARD.md"}
WP_FIELDS = ("id", "name", "purpose", "inputs", "work", "deliverables", "owner", "positive_tests", "negative_tests", "done_criteria",
             "evidence", "unverified", "next", "state")
DIMENSIONS = ("designed", "implemented", "normal_pass", "abnormal_pass", "real_data", "independent_audit", "operational")
DIM_LABEL = {"designed": "設計", "implemented": "実装", "normal_pass": "正常系", "abnormal_pass": "異常系", "real_data": "実データ",
             "independent_audit": "独立監査", "operational": "運用実証"}
MARK = {"yes": "✅", "partial": "◐", "no": "✖"}
REAL_KINDS = ("copied_real_db", "production_read_only")
GATE_FIELDS = ("current_implementation", "synthetic", "repository_sample", "work_real_db", "missing_input", "missing_implementation",
               "audit_method", "done_condition", "next_action")
GATE_LABEL = {"current_implementation": "現在の実装", "synthetic": "合成DBでの検証", "repository_sample": "リポジトリのサンプルでの検証",
              "work_real_db": "Work 実DBでの検証", "missing_input": "不足する入力", "missing_implementation": "不足する実装",
              "audit_method": "独立監査の方法", "done_condition": "完了条件", "next_action": "次に誰が何を行うか"}


def load(path: Path = DATA) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(data: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    states = set(data["states"])
    seen: set[str] = set()
    for p in data["processes"]:
        if not p.get("criteria"):
            problems.append(f"{p['id']}: no acceptance criteria (a process without criteria cannot be counted)")
        for c in p.get("criteria", []):
            if c["verified"] and not c.get("evidence"):
                problems.append(f"{c['id']}: marked verified without evidence")
        for wp in p["work_packages"]:
            missing = [f for f in WP_FIELDS if f not in wp or wp[f] in (None,)]
            if missing:
                problems.append(f"{wp.get('id')}: missing fields {missing}")
                continue
            if wp["id"] in seen:
                problems.append(f"{wp['id']}: duplicate id")
            seen.add(wp["id"])
            if wp["state"] not in states:
                problems.append(f"{wp['id']}: unknown state {wp['state']!r}")
            if wp["state"] in ("accepted", "operational") and not wp["evidence"]:
                problems.append(f"{wp['id']}: {wp['state']} without evidence")
            if wp["state"] == "operational" and p["id"] not in ("P9", "P10"):
                problems.append(f"{wp['id']}: operational is only possible from P9 on")
            for field in ("positive_tests", "negative_tests"):
                if not wp[field]:
                    problems.append(f"{wp['id']}: no {field}")
    ids = {wp["id"] for p in data["processes"] for wp in p["work_packages"]}
    for p in data["processes"]:
        for wp in p["work_packages"]:
            for dep in wp["inputs"]:
                if dep not in ids:
                    problems.append(f"{wp['id']}: depends on unknown {dep}")
    for area in data["db_areas"]:
        for d in DIMENSIONS:
            cell = area["dimensions"].get(d)
            if cell is None or cell["v"] not in MARK:
                problems.append(f"{area['id']}.{d}: needs v in yes/partial/no")
                continue
            if cell["v"] in ("yes", "partial") and not cell["e"]:
                problems.append(f"{area['id']}.{d}: {cell['v']} without evidence")
            if d == "real_data" and cell["v"] == "yes" and not any(k in cell["e"] for k in REAL_KINDS):
                problems.append(f"{area['id']}.real_data: 'yes' needs a real database (copied_real_db / production_read_only) in its evidence")
            if d == "operational" and cell["v"] == "yes" and area["dimensions"]["real_data"]["v"] != "yes":
                problems.append(f"{area['id']}.operational: cannot be yes while real_data is not")
    for g in data["m1_gates"]:
        missing = [f for f in GATE_FIELDS if not g.get(f)]
        if missing:
            problems.append(f"{g['id']}: missing gate fields {missing}")
        if not g["verified"] and not g["work_real_db"].startswith("未"):
            problems.append(f"{g['id']}: not verified, but work_real_db does not say it was not run")
        if g["verified"] and not any(k in g["evidence"] for k in REAL_KINDS):
            problems.append(f"{g['id']}: an M1 gate needs real-data evidence (copied_real_db / production_read_only)")
    return problems


def metrics(data: dict[str, Any]) -> dict[str, Any]:
    procs = {}
    for p in data["processes"]:
        v = sum(1 for c in p["criteria"] if c["verified"] and c.get("evidence"))
        states: dict[str, int] = {}
        for wp in p["work_packages"]:
            states[wp["state"]] = states.get(wp["state"], 0) + 1
        procs[p["id"]] = {"verified": v, "total": len(p["criteria"]), "percent": round(100 * v / len(p["criteria"])), "wp_states": states}
    areas = {a["id"]: {"yes": sum(1 for d in DIMENSIONS if a["dimensions"][d]["v"] == "yes"),
                       "partial": sum(1 for d in DIMENSIONS if a["dimensions"][d]["v"] == "partial")} for a in data["db_areas"]}
    gates = sum(1 for g in data["m1_gates"] if g["verified"])
    return {"processes": procs, "db_areas": areas, "m1": {"verified_gates": gates, "gates": len(data["m1_gates"]), "complete": gates == len(data["m1_gates"])}}


def summary_text(data: dict[str, Any]) -> str:
    """The numbers of the progress documents as ONE string. The final report quotes this string; a test requires the documents to contain it."""
    m = metrics(data)
    procs = " ".join(f"{k}:{v['verified']}/{v['total']}" for k, v in m["processes"].items())
    areas = " ".join(f"{k}:{v['yes']}/7" for k, v in m["db_areas"].items())
    return f"工程 {procs}｜DB {areas}｜M1 {m['m1']['verified_gates']}/{m['m1']['gates']}"


def _list(items: list[str]) -> str:
    return "／".join(items) if items else "なし"


def render_plan(data: dict[str, Any]) -> str:
    out = ["# SOGH 開発マスタープラン（工程P0〜P10・Work Package）", "",
           "> `docs/development_progress.json` から自動生成（`python -m src.db_contract.progress --write`）。手で編集しない。", "",
           "最終目標：大学の公式一次情報を継続的に収集・検証し、対象年度・入試方式ごとに版管理されたDBへ登録し、根拠付きのnote記事を生成し、**人の承認を経て**非公開下書き・公開・訂正できる、再現可能で監査可能な継続運用サービス。"
           "「DB完成」は全国の大学を登録し終えた状態ではなく、**新しい大学・年度・様式を設定で足しても、スキーマと品質保証を作り直さずに済む**状態を指す。", "",
           "```text", "公式情報の取得 → 版管理 → 原典に基づく事実の抽出 → 大学・方式・年度別のDB登録 → 条件・例外の構造化 → 独立QA → DBの安全な有効化",
           "→ 記事企画・生成 → 記事の独立QA → 人間の承認 → note非公開下書き → （別途承認で）公開 → 公式情報の変更監視 → 影響記事の改訂・再検証・訂正", "```", "",
           "進め方：日付ではなく**依存関係と完了条件**で動かす。状態は `" + " / ".join(data["states"]) + "`。`accepted`（受け入れ済み）と `operational`（運用で実証済み）は別。", "",
           "規則：" + "　".join(f"（{i + 1}）{r}" for i, r in enumerate(data["rules"])), ""]
    for p in data["processes"]:
        out += [f"## {p['id']} — {p['name']}（主管：{p['owner']}）", ""]
        for wp in p["work_packages"]:
            out += [f"### {wp['id']} {wp['name']}　`{wp['state']}`", "",
                    f"- **目的**：{wp['purpose']}", f"- **入力・依存**：{_list(wp['inputs'])}", f"- **作業**：{wp['work']}",
                    f"- **成果物**：{_list(wp['deliverables'])}", f"- **担当**：{wp['owner']}",
                    f"- **正例テスト**：{_list(wp['positive_tests'])}", f"- **負例テスト**：{_list(wp['negative_tests'])}",
                    f"- **完了条件**：{wp['done_criteria']}", f"- **完了証拠**：{wp['evidence'] or '（まだ無い）'}",
                    f"- **未検証**：{wp['unverified'] or '（なし）'}", f"- **次の作業**：{wp['next']}", ""]
    out += ["## マイルストーン", "", "| | 内容 | 着手条件 | 完了条件 |", "|---|---|---|---|"]
    out += [f"| {m['id']} | {m['name']} | {m['start_condition']} | {m['done_condition']} |" for m in data["milestones"]]
    return "\n".join(out) + "\n"


def render_progress(data: dict[str, Any]) -> str:
    m = metrics(data)
    out = ["# 開発進捗（受け入れ条件で数える）", "", f"数値の要約（最終報告と同じ文字列）：`{summary_text(data)}`", "",
           "> `docs/development_progress.json` から自動生成。**テスト件数・PR数は進捗ではない。** 進捗＝証拠つきで検証済みの受け入れ条件 ÷ 受け入れ条件の総数。"
           "未確認・未実施・合成データだけの確認は加算しない。", "", "| 工程 | 内容 | 主管 | 検証済み／条件 | 進捗 | WPの状態 |", "|---|---|---|---|---|---|"]
    for p in data["processes"]:
        x = m["processes"][p["id"]]
        states = "、".join(f"{k} {v}" for k, v in sorted(x["wp_states"].items()))
        out.append(f"| {p['id']} | {p['name']} | {p['owner']} | {x['verified']}／{x['total']} | {x['percent']}% | {states} |")
    out += ["", "## 受け入れ条件（工程ごと）", ""]
    for p in data["processes"]:
        out += [f"### {p['id']} {p['name']}", ""]
        for c in p["criteria"]:
            out.append(f"- {'✅' if c['verified'] else '✖'} {c['text']}" + (f"　— 証拠：{c['evidence']}" if c["evidence"] else ""))
        out.append("")
    out += ["## ブロッカーと次の作業（WP単位、未完了のもの）", "", "| WP | 状態 | 未検証 | 次の作業 |", "|---|---|---|---|"]
    for p in data["processes"]:
        for wp in p["work_packages"]:
            if wp["state"] not in ("accepted", "operational"):
                out.append(f"| {wp['id']} {wp['name']} | `{wp['state']}` | {wp['unverified'] or '—'} | {wp['next']} |")
    return "\n".join(out) + "\n"


def render_dashboard(data: dict[str, Any]) -> str:
    m = metrics(data)
    out = ["# DB 完成度ダッシュボード（M1）", "",
           "> `docs/development_progress.json` から自動生成。✅＝証拠つきで達成、◐＝一部（数えない）、✖＝未達。**`実データ` が ✅ になれるのは、実DBのコピー（copied_real_db）か本番の読み取り専用（production_read_only）で確認したときだけ。**"
           "合成DB・リポジトリのサンプルでの成功は実データではない。", "",
           "| 領域 | " + " | ".join(DIM_LABEL[d] for d in DIMENSIONS) + " | 達成（✅の数／7） |", "|---|" + "---|" * (len(DIMENSIONS) + 1)]
    for a in data["db_areas"]:
        out.append(f"| {a['id']} {a['name']} | " + " | ".join(MARK[a["dimensions"][d]["v"]] for d in DIMENSIONS) + f" | {m['db_areas'][a['id']]['yes']}／7 |")
    out += ["", "## 領域ごとの根拠・ブロッカー・次の作業", ""]
    for a in data["db_areas"]:
        out += [f"### {a['id']} {a['name']}", ""]
        for d in DIMENSIONS:
            cell = a["dimensions"][d]
            out.append(f"- {MARK[cell['v']]} {DIM_LABEL[d]}" + (f"：{cell['e']}" if cell["e"] else ""))
        out += [f"- **ブロッカー**：{a['blocker']}", f"- **次の作業**：{a['next']}", ""]
    g = m["m1"]
    out += ["## M1「汎用データベース基盤の完成」の受け入れ条件", "", f"達成 **{g['verified_gates']}／{g['gates']}**。" +
            ("すべて実データで確認された。" if g["complete"] else "**M1 は未達成**（スキーマ設計書・合成DBのテスト・CI成功だけでは完成としない）。"), ""]
    for gate in data["m1_gates"]:
        out.append(f"- {'✅' if gate['verified'] else '✖'} **{gate['id']}** {gate['text']}　— {gate['evidence'] or '証拠なし'}")
    out += ["", "## 8ゲートの詳細（`not_run` を `pass` にしない。実DBが無ければ未達のまま）", ""]
    for gate in data["m1_gates"]:
        out += [f"### {gate['id']} {'✅' if gate['verified'] else '✖'} {gate['text']}", ""]
        out += [f"- **{GATE_LABEL[f]}**：{gate[f]}" for f in GATE_FIELDS]
        out.append("")
    return "\n".join(out) + "\n"


RENDERERS = {"plan": render_plan, "progress": render_progress, "dashboard": render_dashboard}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--summary", action="store_true", help="print the one-line numbers the final report quotes")
    args = parser.parse_args(argv)
    data = load()
    problems = validate(data)
    if problems:
        print("\n".join(problems))
        return 1
    if args.summary:
        print(summary_text(data))
        return 0
    rendered = {k: RENDERERS[k](data) for k in OUTPUTS}
    if args.write:
        for k, path in OUTPUTS.items():
            path.write_text(rendered[k], encoding="utf-8", newline="\n")
        print("written:", ", ".join(p.name for p in OUTPUTS.values()))
        return 0
    stale = [p.name for k, p in OUTPUTS.items() if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != rendered[k]]
    if args.check and stale:
        print("stale (run --write):", ", ".join(stale))
        return 1
    print(json.dumps(metrics(data), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
