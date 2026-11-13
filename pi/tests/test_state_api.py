import json
import threading
import unittest
import urllib.error
import urllib.request

from pi.sogh_state import state_api as s


class StateApiTests(unittest.TestCase):
    def setUp(self):
        self.srv = s.make_server("127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)

    def test_refuses_to_bind_a_non_loopback_address(self):
        for host in ("0.0.0.0", "192.168.11.25", ""):
            with self.assertRaises(ValueError):
                s.make_server(host, 0)

    def test_health(self):
        self.assertEqual(json.load(self.get("/health"))["ok"], True)

    def test_state_reports_only_the_pi_as_observed(self):
        d = json.load(self.get("/state"))
        self.assertEqual(d["devices"]["pi"]["status"], "OBSERVED")
        self.assertEqual(d["devices"]["gaming_pc"]["status"], "NOT_OBSERVED")
        self.assertEqual(d["devices"]["main_pc"]["status"], "NOT_OBSERVED")
        self.assertEqual(d["m1"]["status"], "UNVERIFIED")
        self.assertIsNone(d["m1"]["checked_at_utc"])
        self.assertEqual(d["authority"], {"read_only": True, "formal_acceptance": False, "execution_authorized": False})

    def test_state_has_no_secret_like_keys(self):
        text = json.dumps(json.load(self.get("/state"))).lower()
        for bad in ("password", "token", "secret", "private_key", "ssid"):
            self.assertNotIn(bad, text)

    def test_unknown_path_and_write_methods(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/nope")
        self.assertEqual(e.exception.code, 404)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/state", data=b"{}", method=method)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(e.exception.code, 405)

    def test_missing_measurement_is_none_not_a_guess(self):
        d = s.build_state(pi={"cpu_temp_c": None})
        self.assertIsNone(d["devices"]["pi"]["values"]["cpu_temp_c"])

    def test_clock_sync_is_true_false_or_unknown_never_invented(self):
        self.assertIn(s.measure_pi()["clock_is_ntp_synced"], (True, False, None))

    def test_new_measurements_are_present_and_sane(self):
        v = s.measure_pi()
        for k in ("mem_used_percent", "disk_root_used_percent", "ssh_port_open", "cpu_count"):
            self.assertIn(k, v)
        self.assertTrue(0 <= v["disk_root_used_percent"] <= 100)

    def test_sd_write_volume_is_computed_from_diskstats_and_is_none_when_unknown(self):
        line = "   179       0 mmcblk0 100 0 800 50 200 0 4096 70 0 90 120 0 0 0 0 0 0"  # field 10 (sectors written) = 4096 -> 2 MiB
        self.assertEqual(s._sd_written_mib(line), 2.0)
        self.assertIsNone(s._sd_written_mib("   8  0 sda 1 2 3 4 5 6 7 8"))          # no such device
        self.assertIsNone(s._sd_written_mib(""))                                      # nothing readable
        self.assertIsNone(s._sd_written_mib("179 0 mmcblk0 a b c d e f g h"))         # garbage is not turned into a number

    def test_page_labels_sd_writes_and_unknown_is_not_shown_as_a_number(self):
        self.assertIn("SDカードへの書込", s.INDEX_HTML)
        self.assertIn("sd_written_mib_since_boot==null?null", s.INDEX_HTML.replace(" ", ""))

    def test_page_shows_time_in_japan_time_not_utc(self):
        html = s.INDEX_HTML
        self.assertIn("timeZone:TZ", html.replace(" ", ""))
        self.assertNotIn("測定時刻（UTC）", html)
        self.assertIn('lang="ja"', html)

    def test_index_page_is_static_local_and_labels_unobserved(self):
        r = self.get("/")
        html = r.read().decode("utf-8")
        self.assertEqual(r.status, 200)
        self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
        for needed in ("未観測", "未確認", "表示専用", "取得失敗", "古い可能性", "Asia/Tokyo", "notranslate", "秒ごと", "次の更新まで", "オペレーションセンター", "SOC"):
            self.assertIn(needed, html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("innerHTML", html)
        self.assertNotIn("eval(", html)

    def test_index_page_does_not_accept_writes(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/", data=b"x", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
