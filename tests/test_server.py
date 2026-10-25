import unittest

import testkit as helpers
from testkit import BASE, H

from sawti.studio import Studio


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio()
        cls.c = helpers.client(cls.st)

    def tearDown(self):
        self.st.power_off()

    def test_foreign_host_rejected(self):  # DNS-rebinding defence
        r = self.c.get(BASE + "/api/app", headers={"Host": "evil.example:8765"})
        self.assertEqual(r.status_code, 403)

    def test_write_without_header_rejected(self):  # cross-site "simple" POST defence
        for path in ("/api/power/on", "/api/power/off", "/api/quit", "/api/learning/scan", "/api/presenters"):
            r = self.c.post(BASE + path, data="x", content_type="text/plain")
            self.assertEqual(r.status_code, 403, path)

    def test_foreign_origin_rejected(self):
        r = self.c.post(BASE + "/api/power/on", json={}, headers=dict(H, Origin="https://evil.example"))
        self.assertEqual(r.status_code, 403)

    def test_off_gate(self):
        self.st.power_off()
        r = self.c.get(BASE + "/api/checks")
        self.assertEqual(r.status_code, 503)

    def test_security_headers(self):
        r = self.c.get(BASE + "/")
        self.assertIn("script-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        r.close()

    def test_presenter_delete_by_id_handles_any_name(self):
        self.c.post(BASE + "/api/power/on", json={}, headers=H)
        r = self.c.post(BASE + "/api/presenters", json={"name": "AC/DC <b>Host</b>", "consent": True}, headers=H)
        pid = next(p["id"] for p in r.get_json()["people"] if p["name"].startswith("AC/DC"))
        r = self.c.delete(BASE + f"/api/presenters/{pid}", headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(any(p["id"] == pid for p in r.get_json()["people"]))

    def test_meter_failure_reports_reason(self):
        self.c.post(BASE + "/api/power/on", json={"mode": "zoom"}, headers=H)
        r = self.c.post(BASE + "/api/meter/start", json={}, headers=H)  # no Sawti Show Input yet
        self.assertEqual(r.status_code, 422)
        self.assertIn("Show Input", r.get_json()["error"])
        self.c.post(BASE + "/api/mode", json={"mode": "local"}, headers=H)

    def test_settings_validation(self):
        r = self.c.post(BASE + "/api/settings", json={"loudness_target": -5}, headers=H)
        self.assertEqual(r.status_code, 400)
        r = self.c.post(BASE + "/api/settings", json={"recording_root": "relative/path"}, headers=H)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
