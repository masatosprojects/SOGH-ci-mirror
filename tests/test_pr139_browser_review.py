"""Independent review of Work's local fictional Interview Room v0.1 (PR #139: `research/inbox/work-interview-room/browser.py` + `web/`, stacked on PR #138 which is stacked on PR #135).

Claude-owned QA, kept SEPARATE from the network-forbidden core tests (test_pr138_phase1_review.py): this file starts a real HTTP server on 127.0.0.1 with an ephemeral port and talks to it with http.client.
The only network allowed is a loopback connect (any other address fails the test). DEFINED ONLY when Work's file exists (SOGH_WORK_MRIF_DIR may point at the directory). SYNTHETIC_ONLY: three fictional cases, an injected clock, no files, no vendor API.
Work's own tests are not called. Passing accepts nothing: M1 stays 2/8, NOT ACCEPTED. `known_issue` tests pin a current behaviour that is undecided or differs from the contract."""
import http.client
import json
import os
import re
import socket
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_MRIF_DIR") or REPO / "research" / "inbox" / "work-interview-room")

if (WORK / "browser.py").exists():
    sys.path.insert(0, str(REPO / "sandbox"))
    sys.path.insert(0, str(WORK))
    sys.dont_write_bytecode = True
    import browser  # noqa: E402

    CASE = "fiction-ac-1"
    TEXT = "架空の発表で資料を3回見直しました。"
    WEB = WORK / "web"

    @pytest.fixture(autouse=True)
    def loopback_only(monkeypatch):
        real = socket.socket.connect

        def guarded(self, address, *a, **k):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1"):
                raise AssertionError(f"a non-loopback connection was attempted: {address!r}")
            return real(self, address, *a, **k)

        monkeypatch.setattr(socket.socket, "connect", guarded)

    class Clock:
        def __init__(self):
            self.now = 1_000_000

        def __call__(self):
            return self.now

    class Live:
        """One server per test: 127.0.0.1, port 0, an injected clock."""

        def __init__(self):
            self.clock = Clock()
            self.service = browser.RoomService(self.clock)
            self.server = browser.make_server(0, self.service)
            self.port = self.server.server_port
            self.origin = f"http://127.0.0.1:{self.port}"
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

        def close(self):
            self.server.shutdown()
            self.server.server_close()

        def request(self, method, path, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                conn.request(method, path, body=body, headers=headers or {})
                r = conn.getresponse()
                raw = r.read()
                return r.status, {k.lower(): v for k, v in r.getheaders()}, raw
            except (ConnectionError, http.client.RemoteDisconnected):
                # The server answers a refused POST without reading its body and closes: on Windows the client can see a connection abort before it reads the 403/413. Status None = "no response".
                return None, {}, b""
            finally:
                conn.close()

        def post(self, route, payload, *, origin="same", content_type="application/json", raw=None):
            body = raw if raw is not None else json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": content_type}
            if origin == "same":
                headers["Origin"] = self.origin
            elif origin:
                headers["Origin"] = origin
            status, h, data = self.request("POST", "/api/" + route, body, headers)
            try:
                return status, json.loads(data)
            except ValueError:
                return status, data

        def api(self, route, payload):
            status, data = self.post(route, payload)
            assert status == 200, (route, status, data)
            return data

    @pytest.fixture
    def live():
        server = Live()
        yield server
        server.close()

    def started(live, case=CASE):
        room = live.api("new", {"case_id": case})["room"]
        return live.api("start", {"id": room["id"]})["room"]

    def answer(live, room, key="k1", text=TEXT, **over):
        payload = dict(id=room["id"], turn=room["question"]["turn_id"], generation=room["generation"], text=text, key=key)
        payload.update(over)
        return live.post("answer", payload)

    # ------------------------------------------------------------------ loopback, Host and Origin
    def test_the_server_listens_on_127_0_0_1_only(live):
        assert live.server.server_address[0] == "127.0.0.1"

    def test_a_request_with_a_foreign_host_header_is_refused_for_get_and_post(live):
        for method, path, body in (("GET", "/", None), ("GET", "/api/cases", None), ("POST", "/api/cases", b"{}")):
            status, _, _ = live.request(method, path, body, {"Host": "evil.example", "Origin": live.origin, "Content-Type": "application/json"})
            assert status == 403, (method, path)

    @pytest.mark.parametrize("origin", [None, "http://evil.example", "http://localhost", "null", "http://127.0.0.1:1", "https://127.0.0.1"])
    def test_a_post_without_the_exact_loopback_origin_changes_nothing(live, origin):
        status, data = live.post("new", {"case_id": CASE}, origin=origin)
        assert (status, data) == (403, {"error": "loopback_json_only"}) and live.service.rooms == {}  # F-139-1 RESOLVED at d9231fc: a refused POST with a bounded body now gets its 403, not a connection abort

    def test_a_refused_post_with_a_large_body_always_gets_its_403_and_never_a_connection_abort(live):
        """F-139-1, RESOLVED at d9231fc. Found by mutation: the old server answered a refused POST without reading its body and closed, so a client still sending could see a connection reset instead of the 403. The symptom is timing-dependent,
        so the body is as large as the server allows (16,000 bytes) and the request is repeated: with the body left unread at least one of the 25 is reset on Windows. Every one of them must be a 403 now."""
        body = json.dumps({"case_id": CASE, "pad": "x" * 15_900}).encode()
        assert 15_000 < len(body) <= 16_384
        for origin in ("http://evil.example", None):
            for i in range(25):
                headers = {"Content-Type": "application/json"}
                if origin:
                    headers["Origin"] = origin
                status, _, data = live.request("POST", "/api/new", body, headers)
                assert status == 403, (origin, i)
        assert live.service.rooms == {}

    def test_a_post_that_is_not_json_is_refused_even_with_the_right_origin(live):
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            status, data = live.post("new", {"case_id": CASE}, content_type=ctype)
            assert status == 403 and live.service.rooms == {}, ctype

    def test_localhost_as_a_name_is_refused_so_the_ui_works_only_at_127_0_0_1(live):
        """Strict by design (the printed URL is 127.0.0.1). Pinned so that loosening it is a decision: `localhost` would admit a rebinding name."""
        status, _, _ = live.request("GET", "/", headers={"Host": f"localhost:{live.port}"})
        assert status == 403

    # ------------------------------------------------------------------ static files and headers
    def test_the_page_script_and_style_are_served_with_a_strict_csp_and_nothing_else_is(live):
        for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
            status, h, body = live.request("GET", path, headers={"Host": f"127.0.0.1:{live.port}"})
            assert status == 200 and h["content-type"].startswith(mime) and h["cache-control"] == "no-store" and h["x-content-type-options"] == "nosniff"
            csp = h["content-security-policy"]
            assert "default-src 'self'" in csp and "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe" not in csp
        for path in ("/../browser.py", "/%2e%2e/browser.py", "/web/app.js", "/browser.py", "/BROWSER.md", "/api/state", "/app.js/../browser.py", "/app.js?x=1", "/APP.JS", "/index.html"):
            status, _, _ = live.request("GET", path, headers={"Host": f"127.0.0.1:{live.port}"})
            assert status in (404, 403), path
        # Python's request parser folds a leading `//` into `/`: the result must be the one allowed file, never another one.
        same = live.request("GET", "//app.js", headers={"Host": f"127.0.0.1:{live.port}"})
        assert same[0] == 200 and same[2] == (WEB / "app.js").read_bytes()

    def test_the_static_files_use_no_unsafe_sink_no_media_capture_and_no_external_address():
        sources = {p.name: p.read_text(encoding="utf8") for p in WEB.iterdir() if p.suffix in (".html", ".js", ".css")}
        assert set(sources) == {"index.html", "app.js", "style.css"}
        js = sources["app.js"]
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"", "javascript:"):
            assert sink not in js and sink not in sources["index.html"], sink
        for api in ("getUserMedia", "mediaDevices", "MediaRecorder", "RTCPeerConnection", "WebSocket", "EventSource", "XMLHttpRequest", "localStorage", "sessionStorage", "indexedDB", "navigator.geolocation"):
            assert api not in js, api
        # d9231fc adds ONE beacon: the release request on page close, to this server's own path with a JSON body. Any other use of it would be a new way out of the page.
        assert js.count("sendBeacon") == 1 and 'navigator.sendBeacon("/api/release"' in js and 'type: "application/json"' in js
        for name, text in sources.items():
            assert not re.search(r"https?://|//cdn|@import|url\(", text), name  # no external address in the page, the script or the style
        assert "<script>" not in sources["index.html"].replace("<script defer src=\"/app.js\"></script>", "")  # no inline script
        assert " style=" not in sources["index.html"] and "onclick=" not in sources["index.html"]

    def test_the_page_says_it_is_a_fictional_practice_with_no_ai_connected_and_an_unofficial_evaluation_all_the_time():
        """B-3, RESOLVED at head d9231fc: the old wording 'AI面接官（モック）' could be read as an AI interviewer; the page now says fictional practice, AI NOT connected, rule-based, unofficial evaluation."""
        html = (WEB / "index.html").read_text(encoding="utf8")
        for must in ("架空の練習", "AI未接続", "非公式の練習評価", "ルールベース模擬面接官", "外部API", "カメラ", "マイク", "録音"):
            assert must in html, must
        assert "AI面接官（モック）" not in html and not re.search(r"(?<!ルールベース模擬)AI面接官", html)  # no bare 'AI interviewer' left
        status = (WEB / "app.js").read_text(encoding="utf8")
        assert "模擬接続" in status  # the status line never claims a live connection

    def test_the_script_hides_the_room_while_the_tab_is_in_the_background_and_shows_it_only_after_a_fresh_state_response():
        """B-2 (static part only). The real background/restore of a tab in a real browser is a separate check (see the review record); this only pins the script's logic."""
        js = (WEB / "app.js").read_text(encoding="utf8")
        for must in ('addEventListener("visibilitychange"', "document.hidden", "needsValidation = true", 'el("room").hidden = true', 'addEventListener("focus", revalidate)', 'action === "state"', "needsValidation = false"):
            assert must in js, must
        assert "el(\"room\").hidden = document.hidden || needsValidation" in js  # the room cannot be shown while hidden or unvalidated, whatever the last response said

    def test_every_listed_case_is_visibly_fictional(live):
        status, h, body = live.request("GET", "/api/cases", headers={"Host": f"127.0.0.1:{live.port}"})
        cases = json.loads(body)["cases"]
        assert status == 200 and len(cases) == 3
        for c in cases:
            assert "架空" in c["name"] and isinstance(c["seconds"], int), c

    # ------------------------------------------------------------------ malformed input
    def test_oversized_malformed_and_non_object_bodies_are_refused_without_a_server_error(live):
        assert live.post("new", None, raw=b"x" * 16_385)[0] in (413, None)
        for raw in (b"", b"not json", b"\xff\xfe\x00", b"[]", b'"x"', b"null", b"123"):
            status, data = live.post("new", None, raw=raw)
            assert status in (400, 413, None), (raw, status)
        for payload in ({}, {"case_id": 7}, {"case_id": "no-such-case"}, {"case_id": ["a"]}):
            assert live.post("new", payload)[0] == 400, payload
        assert live.service.rooms == {}

    def test_a_malformed_id_or_an_unknown_operation_is_refused_cleanly(live):
        room = started(live)
        for payload in ({"id": ["x"]}, {"id": {}}, {}):
            assert live.post("state", payload)[0] == 400, payload  # unhashable or missing: a clean 400, not a server error
        for unknown in (None, 7, "0" * 32, "x"):
            assert live.post("state", {"id": unknown}) == (200, {"error": "session_expired"}), unknown
        assert live.post("no-such-route", {"id": room["id"]})[1] == {"error": "unknown_operation"}

    # ------------------------------------------------------------------ the room flow through HTTP
    def test_the_whole_flow_new_start_answer_end_feedback_retry_works_and_ends_with_five_aspects(live):
        room = started(live)
        assert room["state"] == "in_progress" and room["question"] and room["feedback"] is None and room["answered"] == 0
        while room["state"] == "in_progress" and room["question"]:
            live.clock.now += 3000
            status, out = answer(live, room, key=f"k{live.clock.now}")
            assert status == 200 and "error" not in out, out
            room = out["room"]
        if room["state"] != "ended":
            room = live.api("end", {"id": room["id"]})["room"]
        assert room["state"] == "ended" and len(room["feedback"]["items"]) == 5 and room["question"] is None
        old = room["id"]
        again = live.api("retry", {"id": old})["room"]
        assert again["id"] != old and again["answered"] == 0 and again["feedback"] is None
        assert live.post("state", {"id": old}) == (200, {"error": "session_expired"})

    def test_a_double_submit_with_the_same_key_is_one_answer_and_is_reported_as_a_replay(live):
        room = started(live)
        status, first = answer(live, room)
        assert status == 200 and first["replayed"] is False and first["room"]["answered"] == 1
        for _ in range(3):
            live.clock.now += 700  # a real retransmission arrives later: the service re-uses the first accepted time
            status, again = answer(live, room)
            assert status == 200 and again["replayed"] is True and again["room"]["answered"] == 1

    def test_two_different_keys_for_the_same_question_commit_once(live):
        room = started(live)
        assert answer(live, room, key="a")[1]["room"]["answered"] == 1
        status, out = answer(live, room, key="b")
        assert status == 200 and out["error"] in ("stale_generation", "stale_turn") and out["room"]["answered"] == 1

    def test_the_same_key_with_another_text_is_a_conflict_and_the_first_answer_stands(live):
        room = started(live)
        answer(live, room)
        status, out = answer(live, room, text=TEXT + "改ざん")
        assert status == 200 and out["error"] == "idempotency_conflict" and out["room"]["answered"] == 1

    def test_one_rooms_question_cannot_be_answered_through_another_room(live):
        a, b = started(live), started(live)
        assert a["question"]["turn_id"] == b["question"]["turn_id"]  # the fictional cases are deterministic: the first question has the same id in every room, so the room id is what separates sessions
        moved = answer(live, a, key="a1")[1]["room"]  # room A moves on to its next question
        assert moved["question"]["turn_id"] != b["question"]["turn_id"]
        status, out = live.post("answer", dict(id=b["id"], turn=moved["question"]["turn_id"], generation=b["generation"], text=TEXT, key="x"))
        assert status == 200 and out["error"] == "stale_turn" and out["room"]["answered"] == 0  # A's next question cannot be answered inside B
        assert live.post("state", {"id": b["id"]})[1]["room"]["answered"] == 0 and live.post("state", {"id": a["id"]})[1]["room"]["answered"] == 1

    @pytest.mark.parametrize("bad", [True, 1.0, "1", None, [1]])
    def test_a_generation_that_is_not_an_int_is_refused_with_no_effect(live, bad):
        """At head 29a7fa6 (core bfc68cb) the refusal is a `stale_generation` result (HTTP 200 with an error code); the old head raised and the server answered 400. Either way: refused, nothing committed."""
        room = started(live)
        status, out = answer(live, room, generation=bad)
        assert (status == 200 and out.get("error") == "stale_generation") or status == 400
        assert live.api("state", {"id": room["id"]})["room"]["answered"] == 0

    def test_every_response_forbids_camera_and_microphone_through_permissions_policy(live):
        host = {"Host": f"127.0.0.1:{live.port}"}
        for path in ("/", "/app.js", "/style.css", "/api/cases", "/nothing-here"):
            status, h, _ = live.request("GET", path, headers=host)
            assert h.get("permissions-policy") == "camera=(), microphone=()", (path, status)
        status, h, _ = live.request("POST", "/api/new", json.dumps({"case_id": CASE}).encode(), {"Origin": live.origin, "Content-Type": "application/json"})
        assert status == 200 and h.get("permissions-policy") == "camera=(), microphone=()"

    def test_when_the_session_has_expired_the_script_clears_the_question_the_feedback_and_the_answer_from_the_page():
        js = (WEB / "app.js").read_text(encoding="utf8")
        block = js[js.index('data.error === "session_expired"'):]
        block = block[:block.index("const error")]
        for must in ('el("answer").value = ""', '"question"', '"items"', '"reason"', 'replaceChildren()', 'el("room").hidden = true'):
            assert must in block, must

    def test_switching_to_text_moves_the_generation_so_a_stale_answer_is_refused_but_a_retransmission_of_a_committed_one_is_not(live):
        room = started(live)
        status, first = answer(live, room, key="before")
        assert status == 200 and first["room"]["answered"] == 1
        moved = live.api("text", {"id": room["id"]})["room"]
        assert moved["media"] == "degraded_text" and moved["generation"] > room["generation"]
        stale = live.post("answer", dict(id=room["id"], turn=first["room"]["question"]["turn_id"], generation=room["generation"], text=TEXT, key="after"))
        assert stale[0] == 200 and stale[1]["error"] == "stale_generation" and stale[1]["room"]["answered"] == 1
        again = answer(live, room, key="before")  # the original operation, with its original generation, re-sent after the switch
        assert again[0] == 200 and again[1]["replayed"] is True and again[1]["room"]["answered"] == 1
        fresh = live.post("answer", dict(id=room["id"], turn=moved["question"]["turn_id"], generation=moved["generation"], text=TEXT, key="after2"))
        assert fresh[0] == 200 and "error" not in fresh[1]

    def test_a_newer_generation_is_refused_and_the_room_is_unchanged(live):
        room = started(live)
        status, out = answer(live, room, generation=room["generation"] + 4)
        assert status == 200 and out["error"] == "stale_generation" and out["room"]["answered"] == 0

    def test_a_script_in_an_answer_is_returned_as_json_data_and_never_as_markup(live):
        room = started(live)
        evil = "<script>alert(1)</script>\"><img src=x onerror=alert(1)>"
        status, out = answer(live, room, text=evil)
        assert status == 200 and "error" not in out
        status, h, body = live.request("POST", "/api/state", json.dumps({"id": room["id"]}).encode(), {"Origin": live.origin, "Content-Type": "application/json"})
        assert h["content-type"].startswith("application/json") and h["x-content-type-options"] == "nosniff"

    def test_a_contact_string_in_an_answer_is_masked_in_what_the_server_sends_back(live):
        room = started(live)
        status, out = answer(live, room, text=TEXT + " 連絡先は taro@example.com と 090-1234-5678 です。")
        assert status == 200 and "taro@example.com" not in json.dumps(out, ensure_ascii=False) and "090-1234-5678" not in json.dumps(out, ensure_ascii=False)

    def test_the_follow_up_question_quotes_the_answer_by_unicode_code_points_of_the_masked_text(live):
        """The existing engine's follow-up quotes the candidate's own (masked) words with `quote: [start, end]`. The browser must not recompute positions (BROWSER.md): the positions are in code points of the masked text, not UTF-16 units."""
        room = started(live)
        text = "🙂" + TEXT  # an astral character: one code point, two UTF-16 units
        out = answer(live, room, text=text)[1]["room"]
        q = out["question"]
        if q.get("quote"):
            start, end = q["quote"]
            assert 0 <= start <= end <= len(text)  # Python len() counts code points
            assert not re.search(r"\.quote\b|\[\s*['\"]quote['\"]\s*\]", (WEB / "app.js").read_text(encoding="utf8"))  # the browser never reads the position, so it cannot re-derive it

    # ------------------------------------------------------------------ expiry, limits and time
    def test_a_fifth_room_is_refused_until_a_setup_room_expires_after_60_seconds(live):
        for _ in range(4):
            live.api("new", {"case_id": CASE})
        assert live.post("new", {"case_id": CASE}) == (200, {"error": "room_limit"})
        live.clock.now += 60_001
        assert "room" in live.api("new", {"case_id": CASE}) and len(live.service.rooms) == 1

    def test_b1_resolved_rooms_nobody_polls_are_released_after_60_seconds_while_a_polled_room_keeps_its_slot(live):
        """B-1 (reproduced at 29a7fa6: four reloads locked all four slots for about 22 minutes), RESOLVED at d9231fc: a setup or in-progress room with no request for more than 60 s is released.
        The page polls every second while visible, so a live room is never idle; a room whose page was reloaded or closed is."""
        rooms = [started(live) for _ in range(4)]  # four starts, each followed by a reload that forgets the id
        keep = rooms[0]
        for _ in range(2):  # 60 s of clock, polling only the first room every 30 s
            live.clock.now += 30_000
            live.api("state", {"id": keep["id"]})
        assert len(live.service.rooms) == 4  # exactly 60 s idle is still inside the lease (strictly more than 60 s releases)
        live.clock.now += 1
        assert "room" in live.api("new", {"case_id": CASE})  # the sweep ran in dispatch: the three idle rooms are gone, so a slot is free
        assert keep["id"] in live.service.rooms and len(live.service.rooms) == 2
        assert live.post("state", {"id": rooms[1]["id"]}) == (200, {"error": "session_expired"})

    def test_b1_the_release_request_frees_a_room_at_once_only_with_the_loopback_origin_and_harms_nothing_else(live):
        rooms = [started(live) for _ in range(4)]
        assert live.post("new", {"case_id": CASE}) == (200, {"error": "room_limit"})
        for origin in (None, "http://evil.example", "http://localhost"):  # a foreign page cannot release (or probe) a room
            status, data = live.post("release", {"id": rooms[0]["id"]}, origin=origin)
            assert status in (403, None) and rooms[0]["id"] in live.service.rooms, origin
        assert live.post("release", {"id": rooms[0]["id"]}) == (200, {"released": True}) and rooms[0]["id"] not in live.service.rooms
        assert "room" in live.api("new", {"case_id": CASE})  # the slot is free without waiting for the lease
        assert live.post("release", {"id": rooms[0]["id"]}) == (200, {"released": True})  # releasing an unknown or already released id is harmless and says nothing about other rooms
        assert live.post("release", {"id": "0" * 32}) == (200, {"released": True})
        assert live.post("release", {"id": ["x"]})[0] == 400 and live.post("release", {})[0] == 400
        assert all(r["id"] in live.service.rooms for r in rooms[1:])  # the other rooms were not touched

    def test_known_issue_pr139_an_in_progress_room_nobody_polls_for_more_than_60_seconds_is_lost(live):
        """F-139-5 (informational, a consequence of the B-1 fix). A visible page polls every second, so this does not happen while the user looks at it. But a tab left in the BACKGROUND stops polling (the script hides the room and revalidates on return),
        so a user who switches away for more than 60 s mid-interview comes back to `session_expired` and loses the practice, although the interview clock would still allow answers. Probably intended (R7 reconnect TTL is 60 s); pinned so it is a decision, not a surprise."""
        room = started(live)
        live.clock.now += 61_000
        assert live.post("state", {"id": room["id"]}) == (200, {"error": "session_expired"})

    def test_b1_start_is_idempotent_so_a_failed_start_can_be_retried_in_the_same_room(live):
        """F-139-2, RESOLVED at d9231fc: `start` on a room that is already running does nothing, so retrying after a lost response neither restarts the clock nor issues a second first question."""
        created = live.api("new", {"case_id": CASE})["room"]
        first = live.api("start", {"id": created["id"]})["room"]
        live.clock.now += 7000
        again = live.api("start", {"id": created["id"]})["room"]
        assert first["state"] == again["state"] == "in_progress" and again["generation"] == first["generation"] and again["question"] == first["question"]
        assert first["remaining"] - again["remaining"] == 7  # the clock was not restarted by the retry

    def test_an_ended_room_keeps_its_feedback_600_seconds_then_the_session_is_gone(live):
        room = started(live)
        ended = live.api("end", {"id": room["id"]})["room"]
        assert ended["state"] == "ended" and len(ended["feedback"]["items"]) == 5
        live.clock.now += 600_000
        assert live.api("state", {"id": room["id"]})["room"]["feedback"] is not None  # exactly 600 s: still there
        live.clock.now += 1
        assert live.post("state", {"id": room["id"]}) == (200, {"error": "session_expired"}) and live.service.rooms == {}

    def advance_polling(live, room, milliseconds, step=30_000):
        """Move the injected clock the way a visible page does: with a state request at least every 30 s (the page polls every second), so the 60 s lease never releases the room."""
        while milliseconds > 0:
            delta = min(step, milliseconds)
            live.clock.now += delta
            milliseconds -= delta
            live.api("state", {"id": room["id"]})

    def test_the_answer_is_taken_to_the_end_of_the_grace_and_refused_one_millisecond_after(live):
        room = started(live)
        deadline = room["remaining"] * 1000
        advance_polling(live, room, deadline + 120_000)
        status, out = answer(live, room, key="in-grace")
        assert status == 200 and "error" not in out
        room2 = started(live)
        advance_polling(live, room2, room2["remaining"] * 1000 + 120_001)
        status, out = answer(live, room2, key="late")
        assert status == 200 and out.get("error") in ("answer_after_grace", "session_expired", "not_in_progress") or out["room"]["state"] == "ended"
        assert out["room"]["answered"] == 0 if "room" in out else True

    def test_the_remaining_time_comes_from_the_injected_server_clock_not_from_the_browser(live):
        room = started(live)
        before = room["remaining"]
        live.clock.now += 5000
        after = live.api("state", {"id": room["id"]})["room"]["remaining"]
        assert before - after == 5

    def test_the_server_never_writes_the_answer_or_the_request_body_to_a_log(live, capsys):
        room = started(live)
        answer(live, room, text="ログに出てはいけない回答QQQ999")
        live.post("new", None, raw=b"{broken QQQ999")
        out = capsys.readouterr()
        assert "QQQ999" not in out.out and "QQQ999" not in out.err
