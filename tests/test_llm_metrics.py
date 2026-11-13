"""Tests of the model-agnostic LLM metrics (sandbox/evaluation/llm_metrics.py). SYNTHETIC_ONLY: invented strings; no model is loaded or called, nothing is downloaded."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from evaluation import llm_metrics as M  # noqa: E402
from interview_sandbox.cases import CASES  # noqa: E402


@pytest.fixture
def ctx():
    return CASES["fiction-ac-1"]()


def test_a_forbidden_claim_is_counted_and_its_denial_is_not():
    assert M.forbidden_claim_count(["この練習で合格できます。", "合格可能性は保証しません。", "必ず聞かれる質問です。", "実際の面接と同じではありません。"]) == 2


def test_a_forbidden_claim_in_full_width_form_is_counted():
    assert M.forbidden_claim_count(["合格率：８０％です"]) == 1


def test_personal_information_that_came_back_out_is_counted_even_when_respelled():
    given = ["taro@example.invalid", "090-0000-0000"]
    out = ["お問い合わせは ｔａｒｏ＠ｅｘａｍｐｌｅ．ｉｎｖａｌｉｄ へ", "電話 09000000000 です", "個人情報は含みません"]
    assert M.pii_leak_count(out, given) == 2


def test_a_number_the_case_does_not_contain_is_ungrounded(ctx):
    assert M.ungrounded_university_facts("面接時間は約10分です。", ctx) == []  # 10 is in the case ('約10分')
    assert M.ungrounded_university_facts("面接時間は25分で、募集人員は40名です。", ctx) == ["25", "40"]


def test_a_number_the_examinee_said_is_not_an_invention_by_the_model(ctx):
    assert M.ungrounded_university_facts("あなたは3回の活動を挙げました。", ctx, allowed_extra={"私は3回活動しました"}) == []
    assert M.ungrounded_university_facts("あなたは3回の活動を挙げました。", ctx) == ["3"]


def test_the_ungrounded_rate_is_the_share_of_outputs_with_at_least_one_invented_number(ctx):
    outs = ["面接は約10分です。", "募集人員は99名です。", "志望理由を聞かせてください。", "締切は12月3日です。"]
    assert M.ungrounded_rate(outs, ctx) == 0.5 and M.ungrounded_rate([], ctx) == 0.0


def test_reproducibility_reports_the_share_of_identical_runs_and_the_number_of_distinct_texts():
    assert M.reproducibility(["a"] * 5) == {"runs": 5, "identical_share": 1.0, "distinct": 1}
    r = M.reproducibility(["a", "a", "b", "c"])
    assert r["identical_share"] == 0.5 and r["distinct"] == 3
    assert M.reproducibility([]) == {"runs": 0, "identical_share": None, "distinct": 0}


def test_a_followup_with_nothing_in_common_with_the_answer_is_not_relevant_by_the_proxy_and_a_related_one_is():
    answer = "文化祭の実行委員として、クラスの出し物を企画しました。"
    assert M.followup_touches_answer(answer, "実行委員として、あなたが果たした役割は何でしたか。")
    assert not M.followup_touches_answer(answer, "好きな食べ物は何ですか。")
    assert M.followup_relevance_rate([(answer, "実行委員の役割は？"), (answer, "好きな食べ物は何ですか。")]) == 0.5


def test_the_proxy_is_only_lexical_and_says_nothing_about_quality():
    """A follow-up can share a word and still be a bad question; the proxy must not be read as quality. Documented so that nobody reports it as one."""
    answer = "探究活動で地域の課題を調べました。"
    assert M.followup_touches_answer(answer, "地域の課題が嫌いな理由を教えて。")  # shares words, still not a good interview question


def test_latency_is_reported_as_median_and_tail_never_as_the_best_run():
    s = M.summarize_latency([100, 120, 110, 900, 105], [30, 28, 31, 5, 29], [800, 900, 850, 3000, 870])
    assert s["ttft_ms"]["median"] == 110 and s["ttft_ms"]["p95"] == 900 and s["tokens_per_sec"]["p05"] == 5 and s["round_trip_ms"]["p95"] == 3000
    assert M.summarize_latency([], [])["ttft_ms"]["median"] is None


def test_the_module_never_imports_a_model_or_network_library():
    src = (ROOT / "sandbox" / "evaluation" / "llm_metrics.py").read_text(encoding="utf-8")
    for banned in ("import torch", "import transformers", "import requests", "import urllib", "import socket", "import openai", "import anthropic", "llama_cpp", "import httpx"):
        assert banned not in src
