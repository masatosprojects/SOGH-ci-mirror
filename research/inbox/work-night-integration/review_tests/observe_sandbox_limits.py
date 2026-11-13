"""Characterisations of residual limits; a confirmed weakness is NOT a quality pass."""
from dataclasses import replace
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'sandbox'))
from interview_sandbox import InterviewSession, get_case
from experience_report import contract as c

s = InterviewSession(get_case('fiction-ac-1'))
t = s.start()
s.answer(t.turn_id, '私はいろいろ1回頑張りました。', 1)
s.end()
clarity = next(i for i in s.feedback().items if i.key == 'clarity')
r = c.Report(reporter_key='fictional-probe', university='架空大学', faculty='架空学部', method='架空方式', fiscal_year=2027,
    phase='unknown', interview_format='unknown', duration_minutes=None, interviewers=None,
    questions=(c.Question('架空の質問'),), overall_certainty='unknown', consent=c.Consent())
bad = replace(r, phase='not-a-phase', interview_format='not-a-format', overall_certainty='not-certainty')
print(json.dumps({'labels': ['SYNTHETIC_ONLY', 'SELF_VALIDATED'], 'rubric_version': s.feedback().rubric_version,
    'numeric_vague_answer_clarity': clarity.stage,
    'numeric_vague_answer_limitation_confirmed': clarity.stage == 'できている',
    'bad_enums_validation_errors': c.validate(bad),
    'bad_enums_accepted_by_contract_validator': not c.validate(bad),
    'work_http_adapter_rejects_input_enums': 'covered by test_demo.py, phase not user-settable',
    'quality_pass': False, 'human_validity': 'NOT_RUN'}, ensure_ascii=False, indent=2))
