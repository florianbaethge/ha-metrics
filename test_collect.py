"""Trockenlauf: prueft History-Aufbau und Delta-Berechnung ueber zwei Tage."""
import io, json, os, shutil, sys, urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TMP = "/tmp/metrics_test"
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

STARS = {"d1": 7, "d2": 9}
DL = {"d1": 18, "d2": 25}
DAY = {"v": "d1"}


class FakeResp(io.BytesIO):
    headers = {"Link": ""}
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else req
    d = DAY["v"]
    if "/traffic/views" in url:
        body = {"count": 120, "uniques": 40, "views": [{"timestamp": "2026-08-10T00:00:00Z", "count": 12, "uniques": 5}]}
    elif "/traffic/clones" in url:
        body = {"count": 30, "uniques": 11, "clones": []}
    elif "/traffic/popular" in url:
        body = []
    elif "/stargazers" in url:
        body = [{"starred_at": "2026-08-11T09:00:00Z", "user": {"login": "someone"}}]
    elif "/forks" in url:
        body = []
    elif "/releases" in url:
        body = [{"tag_name": "v1.2.0", "name": "v1.2.0", "published_at": "2026-08-11T00:00:00Z",
                 "prerelease": False, "html_url": "http://x",
                 "assets": [{"name": "a.zip", "download_count": DL[d]}]}]
    elif "/issues" in url and "state=closed" in url:
        body = []
    elif "/issues" in url:
        body = [
            {"number": 1, "title": "Bug", "user": {"login": "u"}, "created_at": "2026-08-01T00:00:00Z",
             "updated_at": "2026-08-01T00:00:00Z", "comments": 2, "labels": [], "html_url": "http://i/1"},
            {"number": 2, "title": "PR", "user": {"login": "u"}, "created_at": "2026-08-02T00:00:00Z",
             "updated_at": "2026-08-02T00:00:00Z", "comments": 0, "labels": [], "html_url": "http://p/2",
             "pull_request": {"url": "x"}, "draft": False},
        ]
    else:  # /repos/<full>
        body = {"description": "test", "default_branch": "main", "stargazers_count": STARS[d],
                "forks_count": 1, "subscribers_count": 0, "pushed_at": "2026-08-11T00:00:00Z",
                "archived": False}
    return FakeResp(json.dumps(body).encode())


import collect
collect.DATA_DIR = TMP
collect.REPOS = ["simple_irrigation"]

with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
    DAY["v"] = "d1"
    collect.main()
    # Tag 2 simulieren: History-Datum des ersten Laufs zurueckdatieren
    p = os.path.join(TMP, "simple_irrigation.json")
    doc = json.load(open(p))
    doc["history"][0]["date"] = "2026-08-10"
    json.dump(doc, open(p, "w"))
    DAY["v"] = "d2"
    collect.main()

idx = json.load(open(os.path.join(TMP, "index.json")))
r = idx["repos"][0]
print("\n--- Ergebnis ---")
print("stars:", r["stars"], "| delta stars:", r["delta_vs_prev_day"]["stars"])
print("downloads:", r["downloads_total"], "| delta:", r["delta_vs_prev_day"]["downloads_total"])
print("issues:", r["open_issues_count"], "| prs:", r["open_prs_count"])
print("views_14d:", r["views_14d"], "| prev_date:", r["prev_date"])
doc = json.load(open(os.path.join(TMP, "simple_irrigation.json")))
print("history-Eintraege:", len(doc["history"]), [h["date"] for h in doc["history"]])
print("errors:", doc["current"]["errors"])

assert r["delta_vs_prev_day"]["stars"] == 2, "Star-Delta falsch"
assert r["delta_vs_prev_day"]["downloads_total"] == 7, "Download-Delta falsch"
assert r["open_issues_count"] == 1 and r["open_prs_count"] == 1, "Issue/PR-Trennung falsch"
assert len(doc["history"]) == 2, "History haette 2 Eintraege haben muessen"
print("\nAlle Pruefungen bestanden.")
