"""Positive and negative cases of the PROPOSED realtime-interview contracts (docs/realtime-interview/INTERFACE_CONTRACTS_V1.md, schemas/realtime_contracts_v1.schema.json).

SYNTHETIC_ONLY: invented identifiers and fictional text. The schema checks STRUCTURE. The rules that need the content (a text equals its SHA, a span exists in the answer, a number appears in the context, the seq has no gap)
are the validator's job (Work's mock foundation, docs/realtime-interview/WORK_IMPLEMENTATION_CONTRACT.md) and are not claimed here. Nothing in this file approves a provider, a cost or a deployment."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs" / "realtime-interview" / "schemas" / "realtime_contracts_v1.schema.json").read_text(encoding="utf-8"))
H = "a" * 64
NOW = "2026-11-03T12:00:00+09:00"


def check(name, obj):
    v = Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})
    return sorted(e.message for e in v.iter_errors(obj))


def ok(name, obj):
    assert check(name, obj) == [], check(name, obj)


def bad(name, obj):
    assert check(name, obj), f"{name} should be refused"


def context():
    return {"contract_version": "interview-context-v2", "snapshot_id": "snap-1", "issuer": "fixture", "created_at": NOW, "expires_at": "2026-12-03T12:00:00+09:00", "context_sha256": H,
            "scope": {"case_id": "fiction-ac-1", "university": "架空第一大学", "faculty": "練習学部", "department": None, "offering": "架空総合型方式", "method": "架空総合型方式", "entry_year": 2027, "exam_year": 2026, "stage": "第1段階"},
            "fiscal_year_mapping": {"target": "sandbox.fiscal_year", "basis": "entry_year", "decided_by": "pending"},
            "official_facts": [{"fact_id": "f1", "label": "面接の有無", "status": "confirmed", "value": "あり", "version_id": "v1",
                                "source_ref": {"document_id": "d1", "revision_id": "r1", "sha256": H, "page": 1, "span_start": 0, "span_end": 5}},
                               {"fact_id": "f2", "label": "面接時間", "status": "unknown", "value": None, "version_id": "v1", "source_ref": None}],
            "experience_reports": {"count": 0, "items": []}, "interview_is_official": True}


def plan():
    return {"plan_id": "p1", "session_id": "s1", "categories": [{"name": "志望理由", "min_questions": 1, "max_questions": 2}], "total_seconds": 600, "max_followups_per_question": 2, "max_total_followups": 5,
            "end_policy": "finish_current_question", "mode": "text", "interviewer_count": 1, "recording": "none"}


def proposal():
    return {"proposal_id": "q1", "session_id": "s1", "after_turn_id": "t2", "answer_turn_id": "t2", "answer_span": [0, 14], "text": "その活動で、あなた自身が果たした役割は何でしたか。", "category": "これまでの活動", "intent": "role",
            "origin": "ai_generated", "grounding": {"official_fact_ids": [], "fact_version_ids": [], "uses_unknown": False}, "claims_official": False,
            "budget": {"followups_used": 0, "followups_remaining": 2, "remaining_ms": 480000, "expected_duration_ms": 30000},
            "proposer": {"provider_id": "mock", "model_id": "mock-1", "prompt_version": "p-0"}, "status": "proposed"}


def validated():
    return {"proposal_id": "q1", "status": "validated", "validated_text": "その活動で、あなた自身が果たした役割は何でしたか。", "validated_text_sha256": H,
            "checks": [{"code": "V-GUARD", "result": "pass"}, {"code": "V-PII", "result": "pass"}], "validator_version": "v-0"}


def event():
    return {"event_id": "e1", "session_id": "s1", "seq": 1, "kind": "final", "turn_id": "t2", "generation_id": 0, "role": "candidate", "origin": "user_input", "question_id": None, "basis": [], "followup_of": None,
            "quote": None, "text": "探究活動です。", "text_status": "final", "t_start_ms": 1000, "t_end_ms": 4000, "source": "stt", "idempotency_key": "k1"}


def audio():
    return {"segment_id": "a1", "session_id": "s1", "turn_id": "t2", "direction": "in", "codec": "pcm16", "sample_rate_hz": 16000, "channels": 1, "t_start_ms": 1000, "t_end_ms": 4000, "storage": "none"}


def speech():
    return {"instruction_id": "i1", "generation_id": 1, "turn_id": "t3", "source": "validated_question", "validated_question_id": "q1", "text": "その活動で、あなた自身が果たした役割は何でしたか。", "text_sha256": H,
            "language": "ja", "interruptible": True, "deadline_ms": 9000}


def avatar():
    return {"instruction_id": "av1", "generation_id": 1, "speech_instruction_id": "i1", "state": "speaking", "gesture": "none", "intensity": 0.2, "ai_label_visible": True, "identity": {"avatar_id": "fiction-avatar-1", "license_ref": "own-work"}}


def consent():
    return {"consent_id": "c1", "session_id": "s1", "subject_pseudonym": "u-1", "age_band": "18plus",
            "scopes": {"audio_processing": True, "video_processing": False, "transcript_retention": "session", "recording_retention": "none", "send_to_provider": [], "experience_sharing": False},
            "consent_text_sha256": H, "granted_at": NOW, "expires_at": "2026-11-04T12:00:00+09:00"}


def feedback():
    return {"report_id": "r1", "session_id": "s1", "rubric_version": "practice-rubric-v1.2", "generator": {"kind": "rule"},
            "items": [{"key": "clarity", "label": "答えの明確さ", "stage": "できている", "reason": "最初の一文が短い。", "evidence": [{"turn_id": "t2", "start": 0, "end": 7}], "improvement_example": "結論を先に。", "uncertainty": "同じ回答なら同じ結果（決定的）"}],
            "coverage": {"planned_categories": ["志望理由"], "asked_categories": ["志望理由"], "unasked_categories": []}, "limits": ["練習用のルーブリックです。"], "inference_from_appearance": False}


def usage():
    return {"usage_id": "u1", "session_id": "s1", "provider_id": "mock", "model_id": "mock-1", "model_version_or_snapshot": "0", "kind": "llm", "t_start_ms": 0, "t_end_ms": 100, "units": {"input_tokens": 10, "output_tokens": 5},
            "price_basis": {"price_version": "fixture", "retrieved_on": "2026-11-03", "currency": "USD"}, "cost_estimate": 0.0, "cost_billed": None, "region": "local", "data_policy_ref": "none", "status": "ok", "retries": 0}


FACTORIES = {"InterviewContextV2": context, "InterviewSessionPlan": plan, "QuestionProposal": proposal, "ValidatedQuestion": validated, "TurnEvent": event, "AudioSegment": audio,
             "SpeechInstruction": speech, "AvatarInstruction": avatar, "ConsentRecord": consent, "FeedbackReportV2": feedback, "ProviderUsageRecord": usage}


def test_the_schema_itself_is_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema({"$defs": SCHEMA["$defs"]})
    assert set(FACTORIES) <= set(SCHEMA["$defs"])


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_each_positive_example_is_accepted(name):
    ok(name, FACTORIES[name]())


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_an_unknown_field_is_refused_everywhere(name):
    o = FACTORIES[name]()
    o["surprise"] = 1
    bad(name, o)


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_a_missing_required_field_is_refused_everywhere(name):
    base = FACTORIES[name]()
    required = SCHEMA["$defs"][name]["required"]
    for key in required:
        o = deepcopy(base)
        del o[key]
        bad(name, o)


def mut(name, fn):
    o = FACTORIES[name]()
    fn(o)
    return o


NEGATIVE = [
    ("InterviewContextV2", "unknown fact with a value", lambda o: o["official_facts"][1].update(value="約10分")),
    ("InterviewContextV2", "unknown fact with a source", lambda o: o["official_facts"][1].update(source_ref=o["official_facts"][0]["source_ref"])),
    ("InterviewContextV2", "confirmed fact without a source", lambda o: o["official_facts"][0].update(source_ref=None)),
    ("InterviewContextV2", "confirmed fact without a value", lambda o: o["official_facts"][0].update(value=None)),
    ("InterviewContextV2", "entry year as a string", lambda o: o["scope"].update(entry_year="2027")),
    ("InterviewContextV2", "a fiscal_year field that must not exist", lambda o: o["scope"].update(fiscal_year=2027)),
    ("InterviewContextV2", "a bad context hash", lambda o: o.update(context_sha256="Z" * 64)),
    ("InterviewContextV2", "another contract version", lambda o: o.update(contract_version="interview-context-v1")),
    ("InterviewContextV2", "mapping basis not named", lambda o: o["fiscal_year_mapping"].update(basis="guess")),
    ("InterviewSessionPlan", "duration out of range", lambda o: o.update(total_seconds=10)),
    ("InterviewSessionPlan", "more follow-ups than the existing limit", lambda o: o.update(max_followups_per_question=3)),
    ("InterviewSessionPlan", "stored recording without a consent", lambda o: o.update(recording="stored")),
    ("InterviewSessionPlan", "no categories", lambda o: o.update(categories=[])),
    ("InterviewSessionPlan", "two interviewers (future only)", lambda o: o.update(interviewer_count=2)),
    ("InterviewSessionPlan", "unknown mode", lambda o: o.update(mode="hologram")),
    ("QuestionProposal", "an unknown fact is used", lambda o: o["grounding"].update(uses_unknown=True)),
    ("QuestionProposal", "claims official without a fact", lambda o: o.update(claims_official=True)),
    ("QuestionProposal", "not marked as AI generated", lambda o: o.update(origin="official")),
    ("QuestionProposal", "already validated", lambda o: o.update(status="validated")),
    ("QuestionProposal", "empty text", lambda o: o.update(text="")),
    ("QuestionProposal", "text too long", lambda o: o.update(text="あ" * 401)),
    ("QuestionProposal", "an intent that is not allowed", lambda o: o.update(intent="intimidate")),
    ("ValidatedQuestion", "validated with a failed check", lambda o: o["checks"].append({"code": "V-GROUND", "result": "fail"})),
    ("ValidatedQuestion", "validated without a hash", lambda o: o.update(validated_text_sha256=None)),
    ("ValidatedQuestion", "replaced by a fallback without naming it", lambda o: o.update(status="replaced_by_fallback")),
    ("ValidatedQuestion", "an unknown check code", lambda o: o["checks"].append({"code": "V-VIBES", "result": "pass"})),
    ("TurnEvent", "a final event whose text is partial", lambda o: o.update(text_status="partial")),
    ("TurnEvent", "a partial event marked final", lambda o: o.update(kind="partial", text_status="final")),
    ("TurnEvent", "negative sequence", lambda o: o.update(seq=-1)),
    ("TurnEvent", "an unknown origin", lambda o: o.update(origin="model_said_so")),
    ("TurnEvent", "no idempotency key", lambda o: o.pop("idempotency_key")),
    ("AudioSegment", "stored without a consent", lambda o: o.update(storage="encrypted_store")),
    ("AudioSegment", "a codec nobody reviewed", lambda o: o.update(codec="mp3")),
    ("AudioSegment", "stereo", lambda o: o.update(channels=2)),
    ("SpeechInstruction", "a validated question without its id", lambda o: o.pop("validated_question_id")),
    ("SpeechInstruction", "a fixed phrase without its id", lambda o: o.update(source="fixed_phrase")),
    ("SpeechInstruction", "free text as a source", lambda o: o.update(source="model_generated")),
    ("SpeechInstruction", "english (initial scope is Japanese)", lambda o: o.update(language="en")),
    ("SpeechInstruction", "no deadline", lambda o: o.pop("deadline_ms")),
    ("AvatarInstruction", "the AI label can be hidden", lambda o: o.update(ai_label_visible=False)),
    ("AvatarInstruction", "a gesture that mirrors the person's emotion", lambda o: o.update(gesture="mirror_user_emotion")),
    ("AvatarInstruction", "no licence for the face", lambda o: o["identity"].update(license_ref="")),
    ("ConsentRecord", "a minor with a provider", lambda o: (o.update(age_band="under18"), o["scopes"]["send_to_provider"].append({"provider_id": "p", "purpose": "x", "data_kinds": ["audio"], "region": "jp", "retention": "0", "training_use": "no"}))),
    ("ConsentRecord", "an unknown age with a stored recording", lambda o: (o.update(age_band="unknown"), o["scopes"].update(recording_retention="days_30"))),
    ("ConsentRecord", "a minor with video", lambda o: (o.update(age_band="under18"), o["scopes"].update(video_processing=True))),
    ("ConsentRecord", "training use not stated", lambda o: o["scopes"]["send_to_provider"].append({"provider_id": "p", "purpose": "x", "data_kinds": ["audio"], "region": "jp", "retention": "0", "training_use": "unknown"})),
    ("ConsentRecord", "no consent text version", lambda o: o.update(consent_text_sha256="x")),
    ("FeedbackReportV2", "an item without evidence", lambda o: o["items"][0].update(evidence=[])),
    ("FeedbackReportV2", "a cannot-judge item that carries invented evidence", lambda o: o["items"][0].update(stage="判定できない", evidence=[{"turn_id": "t2", "start": 0, "end": 7}])),
    ("FeedbackReportV2", "inference from appearance switched on", lambda o: o.update(inference_from_appearance=True)),
    ("FeedbackReportV2", "no uncertainty", lambda o: o["items"][0].update(uncertainty="")),
    ("FeedbackReportV2", "no limits shown", lambda o: o.update(limits=[])),
    ("FeedbackReportV2", "a stage that does not exist", lambda o: o["items"][0].update(stage="合格圏")),
    ("ProviderUsageRecord", "no price basis", lambda o: o.pop("price_basis")),
    ("ProviderUsageRecord", "no model version", lambda o: o.update(model_version_or_snapshot="")),
    ("ProviderUsageRecord", "a negative cost", lambda o: o.update(cost_estimate=-1)),
    ("ProviderUsageRecord", "an unknown kind", lambda o: o.update(kind="telepathy")),
]


@pytest.mark.parametrize("name,why,fn", NEGATIVE, ids=[f"{n}:{w}" for n, w, _ in NEGATIVE])
def test_each_negative_case_is_refused(name, why, fn):
    bad(name, mut(name, fn))


def test_v1_1_a_cannot_judge_item_needs_no_evidence_and_may_not_have_any():
    """R4 (Issue #75): zero or one answer gives the stage "判定できない" (feedback.NOT_ENOUGH). The report must be able to say so without a fabricated span, and must not smuggle a span in."""
    o = feedback()
    o["items"] = [{"key": "clarity", "label": "答えの明確さ", "stage": "判定できない", "reason": "回答が足りません。", "evidence": [], "improvement_example": "まず 2〜3 文で答えてみましょう。", "uncertainty": "回答 0 件のため評価していません"}]
    ok("FeedbackReportV2", o)
    o["items"][0]["evidence"] = [{"turn_id": "t2", "start": 0, "end": 1}]
    bad("FeedbackReportV2", o)


def test_the_positive_examples_stay_positive_after_the_negative_mutations_ran():
    for name, factory in FACTORIES.items():
        ok(name, factory())
