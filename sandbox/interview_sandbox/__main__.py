"""Text practice on the command line.  python -m interview_sandbox --case fiction-ac-1            (type your answers)
                                      python -m interview_sandbox --case fiction-ac-1 --script answers.txt   (one answer per line, for a demo; 10 seconds are counted per answer)"""
from __future__ import annotations

import argparse
import sys
import time

from .cases import CASES, get_case
from .engine import InterviewSession
from .feedback import compare


def run(case_id: str, answers: list[str] | None, out=sys.stdout, inp=sys.stdin, profile=None) -> int:
    session = InterviewSession(get_case(case_id), profile=profile)
    print(session.briefing().text(), file=out)
    turn = session.start()
    queue = list(answers) if answers is not None else None
    while turn is not None and session.state == "in_progress":
        print(f"\n[残り約 {session.remaining_seconds // 60} 分 {session.remaining_seconds % 60} 秒]\n面接官（AI 練習用）：{turn.text}", file=out)
        began = time.monotonic()
        if queue is not None:
            if not queue:
                session.end("script_finished")
                break
            reply, elapsed = queue.pop(0), 10
        else:
            print("あなた（空の行で終了）：", end="", file=out, flush=True)
            reply = inp.readline().rstrip("\n")
            elapsed = int(time.monotonic() - began)
            if not reply:
                session.end("user")
                break
        result = session.answer(turn.turn_id, reply, min(elapsed, 3600))
        for n in result.notices:
            print(f"（お知らせ）{n.text}", file=out)
        turn = result.next_turn
    if session.state != "ended":
        session.end("closed")
    print("\n練習を終了しました。\n", file=out)
    report = session.feedback()
    print(report.text(), file=out)
    print("\n同じ条件でもう一度練習する場合は、同じコマンドをもう一度実行してください（前回との比較は `compare` を使います）。", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--case", choices=sorted(CASES), default="fiction-ac-1")
    p.add_argument("--script", help="a text file with one answer per line")
    p.add_argument("--profile", help="a JSON file with your INVENTED 志望理由書 and 活動情報: {\"motivation\": \"...\", \"activities\": [{\"title\": \"...\", \"description\": \"...\"}]}  (read only; nothing is written)")
    a = p.parse_args(argv)
    answers = None
    if a.script:
        answers = [ln.rstrip("\n") for ln in open(a.script, encoding="utf-8") if ln.strip()]
    profile = None
    if a.profile:
        import json
        from .profile import build_profile
        with open(a.profile, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or set(data) - {"motivation", "activities"}:
            raise SystemExit("the profile file has only motivation and activities")
        profile = build_profile(data.get("motivation"), data.get("activities", []))
    return run(a.case, answers, profile=profile)


if __name__ == "__main__":
    raise SystemExit(main())
