"""Work-authored fictional UI adapter tests; not a real-user assessment."""
import importlib.util
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

BASE = Path(__file__).resolve().parents[1]
REPO = BASE.parents[2]
spec = importlib.util.spec_from_file_location('work_demo', BASE / 'demo/server.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def demo():
    return m.Demo(REPO / 'sandbox')


def started(demo):
    sid = demo.dispatch('/api/new', {'case_id': 'fiction-ac-1'})['id']
    turn = demo.dispatch('/api/start', {'id': sid})['turn']
    return sid, turn


def test_no_real_case_or_persistence(demo):
    assert len(demo.dispatch('/api/cases', {})['cases']) == 3
    with pytest.raises(KeyError):
        demo.dispatch('/api/new', {'case_id': 'real-university'})
    assert not demo.sessions


def test_answer_masking_replay_and_clear(demo):
    sid, turn = started(demo)
    email, phone = 'fiction' + '@example.com', '090' + '-1234' + '-5678'
    body = dict(id=sid, turn_id=turn['turn_id'], text='架空の連絡先 ' + email + ' ' + phone, elapsed=30)
    result = demo.dispatch('/api/answer', body)
    assert result['result']['accepted']
    encoded = json.dumps(result)
    assert email not in encoded and phone not in encoded
    assert not demo.dispatch('/api/answer', body)['result']['accepted']
    assert demo.dispatch('/api/reset', {'id': sid})['cleared']
    with pytest.raises(ValueError):
        demo.dispatch('/api/end', {'id': sid})


@pytest.mark.parametrize('changes', [{'elapsed': True}, {'text': 'x' * 2001}, {'elapsed': -1}])
def test_bad_answer_rejected_without_turn_advance(demo, changes):
    sid, turn = started(demo)
    with pytest.raises(ValueError):
        demo.dispatch('/api/answer', dict(id=sid, turn_id=turn['turn_id'], text='架空の回答', elapsed=1, **{} ) | changes)
    assert not demo.sessions[sid]['session'].candidate_turns()


def test_feedback_retry_without_score_claim(demo):
    sid, turn = started(demo)
    demo.dispatch('/api/answer', dict(id=sid, turn_id=turn['turn_id'], text='架空の活動で資料を3回まとめました。学ぶ理由があります。', elapsed=1))
    feedback = demo.dispatch('/api/end', {'id': sid})
    assert len(feedback['feedback']['items']) == 5
    assert feedback['feedback']['limits']
    assert demo.dispatch('/api/retry', {'id': sid})['turn']
    comparison = demo.dispatch('/api/end', {'id': sid})['comparison']
    assert len(comparison) == 5


def test_consent_independent_and_no_storage(demo):
    data = {'question': '架空の質問', 'consent': {'school_internal': True}}
    result = demo.dispatch('/api/report', data)
    assert result['consent_preview'] == {'school_internal': True, 'sogh_internal': False, 'public': False}
    assert result['stored'] is result['published'] is False
    assert not demo.sessions


@pytest.mark.parametrize('changes', [{'consent': {'public': 'false'}}, {'format': 'fake'}, {'certainty': 'always'}, {'duration': True}])
def test_bad_report_contract_inputs(demo, changes):
    with pytest.raises(ValueError):
        demo.dispatch('/api/report', {'question': '架空の質問'} | changes)


def test_http_boundary_and_path_allowlist(demo):
    server = m.ThreadingHTTPServer(('127.0.0.1', 0), m.handler_for(demo))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    try:
        with urllib.request.urlopen(url + '/api/cases') as response:
            assert response.status == 200
            assert response.headers['Cache-Control'] == 'no-store'
        for path, headers, code in [('/api/cases', {'Origin': 'https://untrusted.example'}, 403),
                                    ('/api/cases', {'Host': 'untrusted.example'}, 403),
                                    ('/../server.py', {}, 404)]:
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(urllib.request.Request(url + path, headers=headers))
            assert err.value.code == code
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
