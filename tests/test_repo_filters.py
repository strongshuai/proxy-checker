import unittest
import json
import os
import tempfile
import threading
import urllib.request
from unittest import mock

import server


class RepoFilterTests(unittest.TestCase):
    def setUp(self):
        self.repo = [
            {
                "proxy": "http://a.example:8080",
                "grade": "A",
                "latency": 100,
                "country": "US",
                "ip_type": "residential",
                "target_profile": "generic",
                "recommended_use": "generic",
                "service_reachable": True,
                "api_reachable": True,
                "cf_bypass": True,
            },
            {
                "proxy": "http://b.example:8080",
                "grade": "B",
                "latency": 900,
                "country": "NL",
                "ip_type": "datacenter",
                "target_profile": "openai",
                "recommended_use": "openai",
                "service_reachable": True,
                "api_reachable": False,
                "cf_bypass": False,
            },
            {
                "proxy": "http://c.example:8080",
                "grade": "D",
                "latency": 2500,
                "country": "",
                "ip_type": "unknown",
                "target_profile": "generic",
                "recommended_use": "generic",
                "service_reachable": False,
                "api_reachable": False,
                "cf_bypass": False,
            },
        ]

    def _filter(self, query):
        filters = server.parse_repo_filter_query(query)
        return [item["proxy"] for item in server.apply_repo_filters(self.repo, filters)]

    def test_filters_by_grade_list_and_truthy_flags(self):
        proxies = self._filter({
            "grade": ["A,B"],
            "service": ["1"],
            "cf": ["true"],
        })

        self.assertEqual(proxies, ["http://a.example:8080"])

    def test_filters_by_api_country_ip_type_and_latency(self):
        proxies = self._filter({
            "api": ["1"],
            "country": ["US"],
            "ip_type": ["res"],
            "max_latency": ["150"],
        })

        self.assertEqual(proxies, ["http://a.example:8080"])

    def test_filters_by_datacenter_alias_and_profile(self):
        proxies = self._filter({
            "type": ["dc"],
            "profile": ["openai"],
            "use": ["openai"],
        })

        self.assertEqual(proxies, ["http://b.example:8080"])

    def test_country_truthy_requires_any_country(self):
        proxies = self._filter({"country": ["1"]})

        self.assertEqual(proxies, ["http://a.example:8080", "http://b.example:8080"])

    def test_false_boolean_filter_is_supported(self):
        proxies = self._filter({"service_reachable": ["0"], "grade": ["D"]})

        self.assertEqual(proxies, ["http://c.example:8080"])


class RepoFilterHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.repo_dir = os.path.join(self.tmpdir.name, "repo_data")
        os.makedirs(self.repo_dir)
        self.repo = [
            {
                "proxy": "http://a.example:8080",
                "grade": "A",
                "latency": 100,
                "country": "US",
                "ip_type": "residential",
                "service_reachable": True,
                "api_reachable": True,
                "cf_bypass": True,
            },
            {
                "proxy": "http://b.example:8080",
                "grade": "B",
                "latency": 900,
                "country": "NL",
                "ip_type": "datacenter",
                "service_reachable": True,
                "api_reachable": False,
                "cf_bypass": False,
            },
        ]
        with open(os.path.join(self.repo_dir, "sample.json"), "w", encoding="utf-8") as handle:
            json.dump(self.repo, handle)
        with open(os.path.join(self.repo_dir, "sample.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(item["proxy"] for item in self.repo))

        self.repo_patch = mock.patch.object(server, "REPO_DIR", self.repo_dir)
        self.repo_patch.start()
        self.addCleanup(self.repo_patch.stop)

        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def _url(self, path):
        host, port = self.httpd.server_address
        return f"http://{host}:{port}{path}"

    def test_txt_endpoint_filters_from_json_metadata(self):
        with urllib.request.urlopen(self._url("/api/repo/sample.txt?grade=A&cf=1&ip_type=res"), timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(body, "http://a.example:8080")

    def test_json_endpoint_returns_filtered_repo_objects(self):
        with urllib.request.urlopen(self._url("/api/repo/sample.json?type=dc&country=NL"), timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual([item["proxy"] for item in payload], ["http://b.example:8080"])
        self.assertEqual(payload[0]["ip_type"], "datacenter")


if __name__ == "__main__":
    unittest.main()
