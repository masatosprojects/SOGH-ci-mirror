"""Independent negative tests of Work's PR #93 deliverables: `prepare_isolation.py` (patch isolation) and the loopback demo server `demo/server.py`.

Claude-owned QA for the review of PR #93 (head cb03ff8). The tests are DEFINED ONLY when Work's directory exists (`research/inbox/work-night-integration`, or the directory named by
SOGH_WORK_NIGHT_DIR), so they are absent (not skipped) on a checkout without PR #93 and run once it is merged. SYNTHETIC_ONLY: no database is opened, the source is Work's delivered
code, the demo serves invented cases. Work's files are only read and executed, never edited.

Findings that are real defects of Work's code are pinned as `test_known_issue_*` (they assert the CURRENT behaviour and name the finding): they are not passes of the contract; when Work
fixes the code the test fails on purpose and must be flipped. Everything else asserts the intended safe behaviour.
"""
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_NIGHT_DIR") or REPO / "research" / "inbox" / "work-night-integration")
FAQ_V3 = REPO / "research" / "inbox" / "work-faq-v3" / "pipeline"
PRESENT = (WORK / "prepare_isolation.py").exists() and (WORK / "demo" / "server.py").exists() and FAQ_V3.exists()

if PRESENT:
    GUARDED_FILES = ("admissions_pipeline/store.py", "admissions_pipeline/generic.py", "admissions_pipeline/revisions.py", "scripts/revise_notices.py")

    def complete_source(tmp, name="src"):
        """Work's delivered pipeline folder (CRLF) plus the empty directories prepare_isolation copies (the delivered folder has no admission_ai / config / tests)."""
        root = tmp / name
        shutil.copytree(FAQ_V3, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for sub in ("admissions_pipeline", "admission_ai", "scripts", "tests", "config"):
            (root / sub).mkdir(exist_ok=True)
        return root

    def isolate(source, out, autocrlf=None):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if autocrlf is not None:
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.autocrlf", GIT_CONFIG_VALUE_0=autocrlf)
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(WORK / "prepare_isolation.py"), "--source-root", str(source), "--output", str(out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)

    def tree_hash(root):
        h = hashlib.sha256()
        for p in sorted(Path(root).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                h.update(str(p.relative_to(root)).encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    # --- the isolation ---------------------------------------------------------------------------------------------------------------------------------------

    def test_the_isolation_patches_a_copy_leaves_the_source_untouched_and_opens_no_database(tmp_path):
        src = complete_source(tmp_path)
        before = tree_hash(src)
        done = isolate(src, tmp_path / "out")
        assert done.returncode == 0, done.stderr[-500:]
        assert tree_hash(src) == before
        out = tmp_path / "out"
        assert "def configure_connection" in (out / "admissions_pipeline/store.py").read_text(encoding="utf-8")
        assert not list(out.rglob("*.sqlite")) and not list(out.rglob("*.db"))

    @pytest.mark.parametrize("name", GUARDED_FILES)
    def test_a_real_change_in_any_of_the_four_checked_files_is_refused_and_nothing_is_created(tmp_path, name):
        src = complete_source(tmp_path)
        (src / name).write_bytes((src / name).read_bytes() + b"\r\n# changed\r\n")
        done = isolate(src, tmp_path / "out")
        assert done.returncode != 0 and "Precondition mismatch" in done.stdout + done.stderr and not (tmp_path / "out").exists()

    def test_a_line_ending_only_difference_is_accepted_and_the_result_has_the_same_text(tmp_path):
        crlf, lf = complete_source(tmp_path, "crlf"), complete_source(tmp_path, "lf")
        for name in GUARDED_FILES:
            (lf / name).write_bytes((lf / name).read_bytes().replace(b"\r\n", b"\n"))
        a, b = isolate(crlf, tmp_path / "a", autocrlf="false"), isolate(lf, tmp_path / "b", autocrlf="false")
        assert a.returncode == 0 and b.returncode == 0
        for name in GUARDED_FILES:
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
            assert b"\r\n" not in (tmp_path / "a" / name).read_bytes()  # with core.autocrlf=false the four files are LF, as Work's README says

    def test_the_patched_text_does_not_depend_on_git_line_ending_settings(tmp_path):
        a, b = isolate(complete_source(tmp_path, "s1"), tmp_path / "t", autocrlf="true"), isolate(complete_source(tmp_path, "s2"), tmp_path / "f", autocrlf="false")
        assert a.returncode == 0 and b.returncode == 0
        for name in GUARDED_FILES:
            assert (tmp_path / "t" / name).read_bytes().replace(b"\r\n", b"\n") == (tmp_path / "f" / name).read_bytes().replace(b"\r\n", b"\n")

    @pytest.mark.parametrize("setting", ["true", "false", "input"])
    def test_the_isolation_bytes_do_not_depend_on_git_autocrlf(tmp_path, setting):
        """PR #93 finding F-2b (fixed in head 2019231): `git apply` used to follow core.autocrlf (CRLF under `true`, LF otherwise). Now the four files are LF whatever the setting."""
        reference = isolate(complete_source(tmp_path, "s0"), tmp_path / "ref", autocrlf="false")
        other = isolate(complete_source(tmp_path, "s1"), tmp_path / "other", autocrlf=setting)
        assert reference.returncode == 0 and other.returncode == 0
        for name in GUARDED_FILES:
            assert (tmp_path / "other" / name).read_bytes() == (tmp_path / "ref" / name).read_bytes() and b"\r\n" not in (tmp_path / "other" / name).read_bytes()

    def test_an_existing_output_is_never_overwritten_and_a_second_run_is_refused(tmp_path):
        src = complete_source(tmp_path)
        assert isolate(src, tmp_path / "out").returncode == 0
        keep = tree_hash(tmp_path / "out")
        again = isolate(src, tmp_path / "out")
        assert again.returncode != 0 and "NEW isolation" in again.stdout + again.stderr and tree_hash(tmp_path / "out") == keep

    @pytest.mark.parametrize("where", ["inside", "inside_via_dotdot", "same", "parent"])
    def test_an_output_inside_or_equal_to_the_source_or_its_parent_is_refused(tmp_path, where):
        src = complete_source(tmp_path)
        out = {"inside": src / "nested", "inside_via_dotdot": src / ".." / "src" / "nested", "same": src, "parent": src.parent}[where]
        before = tree_hash(src)
        assert isolate(src, out).returncode != 0 and tree_hash(src) == before and not (src / "nested").exists()

    def test_a_missing_checked_file_stops_before_anything_is_created(tmp_path):
        src = complete_source(tmp_path)
        (src / "scripts/revise_notices.py").unlink()
        done = isolate(src, tmp_path / "out")
        assert done.returncode != 0 and not (tmp_path / "out").exists()

    def status_of(out):
        return json.loads((Path(out) / ".work-isolation-status.json").read_text(encoding="utf-8"))

    def test_a_failed_copy_leaves_a_failure_marker_and_never_a_completed_one(tmp_path):
        """PR #93 finding F-2a (fixed in head 2019231): a failed run keeps its half-built output but writes `.work-isolation-status.json` with state `failed` and the failing step
        (the output is not deleted automatically: a person must read the marker). A rerun over it is refused."""
        src = complete_source(tmp_path)
        shutil.rmtree(src / "config")
        done = isolate(src, tmp_path / "out")
        status = status_of(tmp_path / "out")
        assert done.returncode != 0 and status["state"] == "failed" and status["step"] == "copy_code" and "completed" not in json.dumps(status)
        assert isolate(src, tmp_path / "out").returncode != 0 and status_of(tmp_path / "out")["state"] == "failed"

    def test_a_successful_run_records_the_patch_and_the_hashes_of_what_it_wrote(tmp_path):
        assert isolate(complete_source(tmp_path), tmp_path / "out").returncode == 0
        status = status_of(tmp_path / "out")
        assert status["state"] == "completed" and status["patch_sha256"] == hashlib.sha256((WORK / "work-current-stage1.patch").read_bytes()).hexdigest()
        assert set(status["output_sha256"]) == set(GUARDED_FILES)
        for name, digest in status["output_sha256"].items():
            assert hashlib.sha256((tmp_path / "out" / name).read_bytes()).hexdigest() == digest

    def test_a_precondition_failure_creates_no_output_so_there_is_no_marker_to_mistake_for_one(tmp_path):
        src = complete_source(tmp_path)
        (src / "admissions_pipeline/store.py").write_bytes((src / "admissions_pipeline/store.py").read_bytes() + b"\r\n# changed\r\n")
        assert isolate(src, tmp_path / "out").returncode != 0 and not (tmp_path / "out").exists()

    def test_applying_the_patch_twice_is_refused(tmp_path):
        assert isolate(complete_source(tmp_path), tmp_path / "out").returncode == 0
        again = subprocess.run(["git", "apply", "--check", str(WORK / "work-current-stage1.patch")], cwd=tmp_path / "out", capture_output=True, text=True)
        assert again.returncode != 0

    # --- the demo server -------------------------------------------------------------------------------------------------------------------------------------

    _spec = importlib.util.spec_from_file_location("pr93_demo_server", WORK / "demo" / "server.py")
    DEMO = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(DEMO)

    @pytest.fixture
    def server():
        demo = DEMO.Demo(REPO / "sandbox")
        httpd = DEMO.ThreadingHTTPServer(("127.0.0.1", 0), DEMO.handler_for(demo))
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        yield httpd.server_port, demo
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=5)

    def call(port, method, path, headers=None, body=None, host="default", announce_only=False):
        """`announce_only`: send the headers (with the Content-Length of `body`) but not the body. The server answers 403/413 without reading the body and closes the socket; a client that
        had already sent the body would get a connection reset (a race on every platform), which says nothing about the answer itself."""
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            c.putrequest(method, path, skip_host=True)
            if host is not None:
                c.putheader("Host", f"127.0.0.1:{port}" if host == "default" else host)
            for k, v in (headers or {}).items():
                c.putheader(k, str(v))
            if body is not None:
                c.putheader("Content-Length", str(len(body)))
            c.endheaders(None if announce_only else body)
            r = c.getresponse()
            return r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read()
        finally:
            c.close()

    def post(port, path, obj, headers=None, announce_only=False):
        return call(port, "POST", path, headers, json.dumps(obj).encode("utf-8"), announce_only=announce_only)

    @pytest.mark.parametrize("host", ["localhost:{p}", "127.0.0.1", "0.0.0.0:{p}", "evil.example", "127.0.0.1:{p}.evil.example", "[::1]:{p}", None])
    def test_a_request_whose_host_is_not_this_loopback_address_and_port_is_refused(server, host):
        port, _ = server
        status, _, body = call(port, "GET", "/api/cases", host=host.format(p=port) if host else None)
        assert status == 403 and b"cases" not in body

    @pytest.mark.parametrize("origin", ["null", "http://evil.example", "https://127.0.0.1:{p}", "http://127.0.0.1:{p}/", "http://localhost:{p}"])
    def test_a_request_from_any_other_origin_is_refused_for_get_and_post(server, origin):
        port, demo = server
        origin = origin.format(p=port)
        assert call(port, "GET", "/api/cases", {"Origin": origin})[0] == 403
        assert post(port, "/api/new", {"case_id": "fiction-ac-1"}, {"Origin": origin}, announce_only=True)[0] == 403 and not demo.sessions

    def test_a_cross_site_form_post_with_a_plain_text_body_is_refused_before_it_reaches_the_session_code(server):
        port, demo = server
        status, _, _ = call(port, "POST", "/api/new", {"Origin": "http://evil.example", "Content-Type": "text/plain"}, b'{"case_id":"fiction-ac-1"}', announce_only=True)
        assert status == 403 and not demo.sessions

    def test_known_issue_pr93_f5_a_post_without_an_origin_header_is_accepted(server):
        """Informational (low): a browser always sends Origin on a cross-site POST, so a web page is stopped; but a non-browser process on the same machine (no Origin) is accepted.
        That is outside this demo's stated protection (loopback only, fictional data) and is pinned only so a later hardening shows up as a deliberate change."""
        port, demo = server
        status, _, body = post(port, "/api/new", {"case_id": "fiction-ac-1"})
        assert status == 200 and len(demo.sessions) == 1 and "id" in json.loads(body)

    @pytest.mark.parametrize("path", ["/", "/app.js", "/style.css", "/api/cases", "/nope"])
    def test_every_response_has_no_store_nosniff_and_a_strict_csp(server, path):
        port, _ = server
        status, headers, _ = call(port, "GET", path)
        assert headers.get("cache-control") == "no-store" and headers.get("x-content-type-options") == "nosniff"
        csp = headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe" not in csp

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "OPTIONS", "PATCH", "TRACE", "HEAD"])
    def test_only_get_and_post_are_served(server, method):
        port, _ = server
        assert call(port, method, "/api/cases")[0] == 501

    @pytest.mark.parametrize("path", ["/../server.py", "/%2e%2e/server.py", "/..%2fserver.py", "//server.py", "/index.html", "/server.py", "/app.js?x=1", "/api/new", "/\\server.py", "/static/../server.py"])
    def test_no_source_file_or_unlisted_path_is_served(server, path):
        port, _ = server
        status, _, body = call(port, "GET", path)
        assert status in (403, 404) and b"class Demo" not in body

    @pytest.mark.parametrize("body,code", [(b"", 413), (b"x" * 16385, 413), (b"{nope", 400), (b"[1,2]", 400), (b"null", 400), (b"\xff\xfe\x00", 400), (b"[" * 9000 + b"]" * 9000, 413)],
                             ids=["empty", "oversize", "bad-json", "array", "null", "bad-utf8", "deep-nesting"])
    def test_a_malformed_or_oversized_body_gets_a_clean_4xx(server, body, code):
        port, demo = server
        status, _, answer = call(port, "POST", "/api/new", None, body, announce_only=(code == 413))
        assert status == code and answer.startswith(b"{") and not demo.sessions

    def test_a_non_numeric_content_length_gets_a_clean_400(server):
        port, _ = server
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest("POST", "/api/new", skip_host=True)
        c.putheader("Host", f"127.0.0.1:{port}")
        c.putheader("Content-Length", "abc")
        c.endheaders()
        assert c.getresponse().status == 400
        c.close()

    @pytest.mark.parametrize("obj", [{"case_id": ["x"]}, {"case_id": {"a": 1}}, {"case_id": 5}, {"case_id": "real-university"}])
    def test_an_unknown_or_mistyped_case_is_a_clean_400_and_opens_no_session(server, obj):
        port, demo = server
        assert post(port, "/api/new", obj)[0] == 400 and not demo.sessions

    def started(port):
        sid = json.loads(post(port, "/api/new", {"case_id": "fiction-ac-1"})[2])["id"]
        turn = json.loads(post(port, "/api/start", {"id": sid})[2])["turn"]["turn_id"]
        return sid, turn

    @pytest.mark.parametrize("turn_id", ["nope", [1], None, 5])
    def test_an_answer_to_a_turn_that_is_not_the_open_one_is_not_accepted_and_not_stored(server, turn_id):
        port, demo = server
        sid, _ = started(port)
        status, _, body = post(port, "/api/answer", {"id": sid, "turn_id": turn_id, "text": "架空の回答", "elapsed": 1})
        result = json.loads(body)
        assert status == 200 and result["result"]["accepted"] is False and result["stored_answer"] is None and not demo.sessions[sid]["session"].candidate_turns()

    @pytest.mark.parametrize("changes", [{"text": 5}, {"text": "   "}, {"elapsed": True}, {"elapsed": 1.5}, {"elapsed": "1"}, {"elapsed": 3601}, {"elapsed": -1}, {"text": "あ" * 2001}])
    def test_an_ill_typed_or_oversized_answer_is_a_clean_400_and_does_not_advance_the_turn(server, changes):
        port, demo = server
        sid, turn = started(port)
        assert post(port, "/api/answer", dict({"id": sid, "turn_id": turn, "text": "架空の回答", "elapsed": 1}, **changes))[0] == 400
        assert not demo.sessions[sid]["session"].candidate_turns()

    def test_an_email_address_and_a_phone_number_never_come_back_in_any_response_field(server):
        port, _ = server
        sid, turn = started(port)
        mail, phone = "taro.yamada" + "@example.com", "090" + "-1234" + "-5678"
        status, _, body = post(port, "/api/answer", {"id": sid, "turn_id": turn, "text": f"架空です。連絡先 {mail} {phone} です。", "elapsed": 5})
        text = body.decode("utf-8")
        assert status == 200 and mail not in text and phone not in text and "090" not in text
        end = post(port, "/api/end", {"id": sid})[2].decode("utf-8")
        assert mail not in end and phone not in end

    def test_at_most_four_practices_are_open_and_a_reset_frees_one(server):
        port, demo = server
        ids = []
        for _ in range(4):
            status, _, body = post(port, "/api/new", {"case_id": "fiction-ac-1"})
            assert status == 200
            ids.append(json.loads(body)["id"])
        assert post(port, "/api/new", {"case_id": "fiction-ac-1"})[0] == 400
        assert post(port, "/api/reset", {"id": ids[0]})[0] == 200
        assert post(port, "/api/new", {"case_id": "fiction-ac-1"})[0] == 200

    def test_a_practice_expires_after_thirty_minutes_without_use(server, monkeypatch):
        port, demo = server
        sid, _ = started(port)
        real = DEMO.time.monotonic
        monkeypatch.setattr(DEMO.time, "monotonic", lambda: real() + 1801)
        assert post(port, "/api/start", {"id": sid})[0] == 400 and not demo.sessions

    @pytest.mark.parametrize("obj", [{"question": ["x"]}, {"question": "q", "consent": []}, {"question": "q", "format": ["individual"]}, {"question": "q", "duration": 1.5}, {"question": "q", "duration": True},
                                     {"question": "q", "consent": {"public": "true"}}, {"question": "q", "consent": {"public": 1}}, {"question": "x" * 301}, {"question": "q", "format": "fake"},
                                     {"question": "q", "certainty": "always"}])
    def test_the_report_endpoint_refuses_every_mistyped_field_with_a_clean_400(server, obj):
        port, _ = server
        assert post(port, "/api/report", obj)[0] == 400

    def test_the_three_consents_are_independent_default_false_and_nothing_is_stored_or_published(server):
        port, _ = server
        for chosen in ({}, {"school_internal": True}, {"sogh_internal": True}, {"public": True}):
            result = json.loads(post(port, "/api/report", {"question": "架空の質問", "consent": chosen})[2])
            assert result["consent_preview"] == {"school_internal": False, "sogh_internal": False, "public": False, **chosen}
            assert result["stored"] is False and result["published"] is False

    def test_the_page_loads_nothing_from_outside_and_uses_no_browser_storage_or_inline_script():
        html = (WORK / "demo" / "index.html").read_text(encoding="utf-8")
        js = (WORK / "demo" / "app.js").read_text(encoding="utf-8")
        assert not re.search(r"(src|href)=[\"']https?://", html) and "<script>" not in html and "onclick=" not in html
        assert not re.search(r"https?://|localStorage|sessionStorage|indexedDB|document\.cookie|eval\(|new Function|innerHTML|insertAdjacentHTML", js)

    def test_the_report_form_offers_every_interview_format_the_contract_knows():
        """PR #93 finding F-1 (fixed in head 2019231): the first <select> used to read `…</option value="individual">個人</option>`, which a browser drops, so a person who had an
        individual interview could not choose it. The form must offer exactly the values of the contract's InterviewFormat, each as a well-formed option with its own text."""
        from typing import get_args
        sys.path.insert(0, str(REPO / "sandbox"))
        from experience_report.contract import InterviewFormat
        html = (WORK / "demo" / "index.html").read_text(encoding="utf-8")
        select = re.search(r'<select id="format">(.*?)</select>', html, re.S).group(1)
        options = re.findall(r'<option value="([^"]*)">([^<]+)</option>', select)
        assert [v for v, _ in options] == ["unknown", "individual", "group", "presentation_then_qa", "online", "other"] and all(t.strip() for _, t in options)
        assert set(v for v, _ in options) == set(get_args(InterviewFormat))
        assert "</option value=" not in select  # no malformed end tag with an attribute
