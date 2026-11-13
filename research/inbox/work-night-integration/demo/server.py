"""Loopback-only fictional demo; no file persistence, vendor API, or live DB."""
import argparse
from dataclasses import asdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import RLock
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parent


def load_sandbox(path):
    sys.path.insert(0, str(Path(path).resolve()))
    from interview_sandbox import CASES, InterviewSession, get_case, compare
    from experience_report import contract
    return CASES, InterviewSession, get_case, compare, contract


class Demo:
    def __init__(self, sandbox):
        self.cases, self.Session, self.case, self.compare, self.contract = load_sandbox(sandbox)
        self.sessions = {}
        self.lock = RLock()

    def dispatch(self, route, data):
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if time.monotonic() - v['touched'] < 1800}
            if route == '/api/cases':
                return {'cases': [{'id': k, 'name': self.case(k).university + '／' + self.case(k).method} for k in self.cases],
                        'mode': 'SYNTHETIC_ONLY', 'persistence': False, 'external_api': False}
            if route == '/api/new':
                if len(self.sessions) >= 4:
                    raise ValueError('同時に開く練習は4件までです。終了した練習を消去してください。')
                session = self.Session(self.case(data['case_id']))
                sid = uuid4().hex
                self.sessions[sid] = {'session': session, 'previous': None, 'touched': time.monotonic()}
                return {'id': sid, 'briefing': asdict(session.briefing())}
            if route == '/api/report':
                return self.report(data)
            sid = data.get('id')
            if sid not in self.sessions:
                raise ValueError('練習が失効しました。架空ケースを選び直してください。')
            entry = self.sessions[sid]
            entry['touched'] = time.monotonic()
            session = entry['session']
            if route == '/api/reset':
                del self.sessions[sid]
                return {'cleared': True}
            if route == '/api/start':
                return {'turn': asdict(session.start()), 'remaining': session.remaining_seconds}
            if route == '/api/answer':
                text = data.get('text', '')
                if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
                    raise ValueError('架空の回答を1〜2000文字で入力してください。')
                elapsed = data.get('elapsed', 30)
                if type(elapsed) is not int or not 0 <= elapsed <= 3600:
                    raise ValueError('経過時間が不正です。')
                result = session.answer(data['turn_id'], text, elapsed)
                response = {'result': asdict(result), 'remaining': session.remaining_seconds,
                            'stored_answer': session.candidate_turns()[-1].text if result.accepted else None}
                if result.ended:
                    response.update(self.feedback(entry))
                return response
            if route == '/api/end':
                session.end()
                return self.feedback(entry)
            if route == '/api/retry':
                if session.state != 'ended':
                    raise ValueError('一度終了してから再挑戦してください。')
                entry['previous'] = session.feedback()
                entry['session'] = session.retry()
                return {'turn': asdict(entry['session'].start()), 'remaining': entry['session'].remaining_seconds}
            raise ValueError('この操作は利用できません。')

    def feedback(self, entry):
        report = entry['session'].feedback()
        return {'feedback': asdict(report), 'comparison': self.compare(entry['previous'], report) if entry['previous'] else None}

    def report(self, data):
        c = self.contract
        fmt = data.get('format', 'unknown')
        certainty = data.get('certainty', 'unknown')
        if fmt not in ('individual', 'group', 'presentation_then_qa', 'online', 'other', 'unknown') or certainty not in ('sure', 'unsure', 'unknown'):
            raise ValueError('選択肢を確認してください。')
        text = data.get('question', '')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300:
            raise ValueError('架空の質問を1〜300文字で入力してください。')
        duration = data.get('duration')
        if duration is not None and (type(duration) is not int or not 1 <= duration <= 240):
            raise ValueError('所要時間が不正です。')
        consent = data.get('consent', {})
        if not isinstance(consent, dict) or any(type(consent.get(k, False)) is not bool for k in ('school_internal', 'sogh_internal', 'public')):
            raise ValueError('同意は項目ごとの選択が必要です。')
        permissions = {k: consent.get(k, False) for k in ('school_internal', 'sogh_internal', 'public')}
        r = c.Report(reporter_key='fictional-demo-reporter', university='架空第一大学', faculty='練習学部', method='架空総合型',
            fiscal_year=2027, phase='unknown', interview_format=fmt, duration_minutes=duration, interviewers=None,
            questions=(c.Question(text, certainty=certainty),), overall_certainty=certainty,
            consent=c.Consent(**permissions, given_at=date.today().isoformat() if any(permissions.values()) else None))
        errors, flags = c.validate(r), c.review_flags(r)
        visible, labels = c.public_visibility(r, flags)
        # The permission preview never publishes or stores the report itself.
        return {'validation_errors': errors, 'review_flags': flags, 'consent_preview': permissions,
            'eligible_under_draft_contract': visible, 'published': False, 'stored': False,
            'labels': labels, 'summary': c.summarize([r])['statement']}


def handler_for(demo):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never write answers, request bodies, tokens or reports into logs.

        def respond(self, status, body, content_type='application/json; charset=utf-8'):
            raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def local_request(self):
            expected = '127.0.0.1:' + str(self.server.server_port)
            return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected

        def do_GET(self):
            if not self.local_request():
                return self.respond(403, {'error': 'loopback_only'})
            if self.path == '/api/cases':
                return self.respond(200, demo.dispatch(self.path, {}))
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}.get(self.path)
            if not name:
                return self.respond(404, {'error': 'not_found'})
            mime = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
            self.respond(200, (ROOT / name).read_bytes(), mime + '; charset=utf-8')

        def do_POST(self):
            if not self.local_request():
                return self.respond(403, {'error': 'loopback_only'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    return self.respond(413, {'error': 'body_too_large'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('request_object_required')
                self.respond(200, demo.dispatch(self.path, data))
            except (ValueError, KeyError, RuntimeError, TypeError):
                self.respond(400, {'error': '入力または操作順を確認してください。'})
    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sandbox-root', required=True, type=Path)
    p.add_argument('--port', type=int, default=8766)
    a = p.parse_args()
    demo = Demo(a.sandbox_root)
    server = ThreadingHTTPServer(('127.0.0.1', a.port), handler_for(demo))
    print('架空データ限定デモ: http://127.0.0.1:' + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        demo.sessions.clear()


if __name__ == '__main__':
    main()
