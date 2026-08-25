#!/usr/bin/env python3
"""
Sammelt taeglich Kennzahlen fuer alle konfigurierten Repos und schreibt sie
als JSON-Historie nach data/.

Wird von .github/workflows/collect.yml aufgerufen.

Token:
  METRICS_TOKEN  Fine-grained PAT. Noetig fuer Traffic (Administration: read).
                 Ohne dieses Token laeuft alles ausser Traffic weiter.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

OWNER = "florianbaethge"
REPOS = [
    "simple_irrigation",
    "bedtime_stories",
    "advanced_cover",
    "deluxe_room_card",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOKEN = os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
API = "https://api.github.com"
GRAPHQL = API + "/graphql"

# Wie viele Tagesschnappschuesse behalten wir pro Repo
HISTORY_KEEP_DAYS = 400


def api(path, params=None, allow_fail=False, accept=None, headers_out=None):
    """Ein GET gegen die GitHub-API. Gibt (data, error) zurueck.

    accept       abweichender Accept-Header, z.B. star+json fuer starred_at.
    headers_out  optionales dict, das die Antwort-Header aufnimmt (fuer Link).
    """
    url = API + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

    req = urllib.request.Request(url)
    req.add_header("Accept", accept or "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "ha-metrics-collector")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if headers_out is not None:
                    headers_out.update(dict(resp.headers))
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            if e.code in (403, 429) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            msg = f"HTTP {e.code} bei {path}: {body}"
            # GitHub nennt bei 403 selbst, welche Berechtigung gereicht haette.
            accepted = (e.headers or {}).get("X-Accepted-GitHub-Permissions")
            if accepted:
                msg += f" [noetig: {accepted}]"
            if allow_fail:
                return None, msg
            print(f"  ! {msg}", file=sys.stderr)
            return None, msg
        except Exception as e:  # noqa: BLE001
            if attempt < 2:
                time.sleep(3)
                continue
            msg = f"{type(e).__name__} bei {path}: {e}"
            if allow_fail:
                return None, msg
            print(f"  ! {msg}", file=sys.stderr)
            return None, msg
    return None, "unbekannt"


def api_all(path, params=None, max_pages=5):
    """Paginiert eine Listen-Endpoint."""
    out = []
    params = dict(params or {})
    params["per_page"] = 100
    for page in range(1, max_pages + 1):
        params["page"] = page
        data, err = api(path, params)
        if err or not isinstance(data, list):
            break
        out.extend(data)
        if len(data) < 100:
            break
    return out


def graphql(query, variables=None):
    """Ein POST gegen die GraphQL-API. Gibt (data, error) zurueck."""
    if not TOKEN:
        return None, "kein Token"

    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(GRAPHQL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "ha-metrics-collector")
    req.add_header("Authorization", f"Bearer {TOKEN}")

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                doc = json.loads(resp.read().decode("utf-8"))
            errs = doc.get("errors")
            if errs:
                return None, "GraphQL: " + "; ".join(e.get("message", "?") for e in errs)[:200]
            return doc.get("data"), None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            if e.code in (403, 429, 502) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return None, f"HTTP {e.code} bei GraphQL: {body}"
        except Exception as e:  # noqa: BLE001
            if attempt < 2:
                time.sleep(3)
                continue
            return None, f"{type(e).__name__} bei GraphQL: {e}"
    return None, "unbekannt"


# Ein Aufruf statt REST-Pagination: last+ASC liefert direkt die neuesten Sterne.
STARGAZERS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    stargazers(last: 100, orderBy: {field: STARRED_AT, direction: ASC}) {
      edges { starredAt node { login } }
    }
  }
}
"""


def recent_stars(full, cutoff):
    """Sterne seit cutoff als [{user, at}] plus Fehlerliste.

    Die Fehlerliste bleibt leer, sobald einer der beiden Wege Daten geliefert
    hat -- ein Fehlversuch, den der andere Weg auffaengt, gehoert nicht in den
    Report.

    GraphQL zuerst: der REST-Endpunkt /stargazers verlangt fuer Fine-grained
    Token 'Contents' und antwortet sonst mit 403, GraphQL kommt mit dem
    Lesezugriff aus, den das Token ohnehin hat. REST bleibt als Rueckfall.
    """
    owner, name = full.split("/", 1)
    errors = []

    data, gerr = graphql(STARGAZERS_QUERY, {"owner": owner, "name": name})
    if gerr:
        errors.append(f"stargazers GraphQL: {gerr}")
    else:
        repo = (data or {}).get("repository") or {}
        edges = (repo.get("stargazers") or {}).get("edges") or []
        return [
            {"user": (e.get("node") or {}).get("login"), "at": e.get("starredAt")}
            for e in edges
            if (e.get("starredAt") or "") >= cutoff
        ], errors

    # --- Rueckfall: REST -------------------------------------------------
    star_accept = "application/vnd.github.star+json"
    headers = {}
    data, serr = api(
        f"/repos/{full}/stargazers",
        {"per_page": 100, "page": 1},
        allow_fail=True,
        accept=star_accept,
        headers_out=headers,
    )
    if serr:
        errors.append(f"stargazers REST: {serr}")
        return [], errors
    if not isinstance(data, list):
        errors.append(f"stargazers REST: unerwartete Antwort {type(data).__name__}")
        return [], errors

    # Bei mehreren Seiten interessiert nur die letzte (neueste Stars)
    link = headers.get("Link", "")
    if 'rel="last"' in link:
        last = link.split("page=")[-1].split(">")[0].split("&")[0]
        page, perr = api(
            f"/repos/{full}/stargazers",
            {"per_page": 100, "page": last},
            allow_fail=True,
            accept=star_accept,
        )
        if isinstance(page, list) and not perr:
            data = page

    return [
        {"user": (s.get("user") or {}).get("login"), "at": s.get("starred_at")}
        for s in data
        if (s.get("starred_at") or "") >= cutoff
    ], []


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_repo(repo):
    full = f"{OWNER}/{repo}"
    print(f"-> {full}")
    now = datetime.now(timezone.utc)
    snap = {
        "repo": full,
        "collected_at": iso(now),
        "date": now.strftime("%Y-%m-%d"),
        "errors": [],
    }

    # --- Basiszahlen ---------------------------------------------------
    info, err = api(f"/repos/{full}")
    if err:
        snap["errors"].append(f"repo: {err}")
        return snap
    snap["description"] = info.get("description")
    snap["default_branch"] = info.get("default_branch")
    snap["stars"] = info.get("stargazers_count", 0)
    snap["forks"] = info.get("forks_count", 0)
    snap["watchers"] = info.get("subscribers_count", 0)
    snap["pushed_at"] = info.get("pushed_at")
    snap["archived"] = info.get("archived", False)

    # --- Issues und PRs (offen) ----------------------------------------
    # /issues liefert beides; PRs haben den Schluessel "pull_request".
    items = api_all(f"/repos/{full}/issues", {"state": "open", "sort": "created"})
    issues, prs = [], []
    for it in items:
        entry = {
            "number": it.get("number"),
            "title": it.get("title"),
            "user": (it.get("user") or {}).get("login"),
            "created_at": it.get("created_at"),
            "updated_at": it.get("updated_at"),
            "comments": it.get("comments", 0),
            "labels": [l.get("name") for l in it.get("labels", [])],
            "url": it.get("html_url"),
        }
        if it.get("pull_request"):
            entry["draft"] = it.get("draft", False)
            prs.append(entry)
        else:
            issues.append(entry)
    snap["open_issues"] = issues
    snap["open_prs"] = prs
    snap["open_issues_count"] = len(issues)
    snap["open_prs_count"] = len(prs)

    # --- Kuerzlich geschlossen (letzte 7 Tage) -------------------------
    since = iso(now - timedelta(days=7))
    closed = api_all(
        f"/repos/{full}/issues",
        {"state": "closed", "since": since, "sort": "updated"},
        max_pages=2,
    )
    snap["recently_closed"] = [
        {
            "number": it.get("number"),
            "title": it.get("title"),
            "is_pr": bool(it.get("pull_request")),
            "closed_at": it.get("closed_at"),
            "url": it.get("html_url"),
        }
        for it in closed
        if it.get("closed_at") and it["closed_at"] >= since
    ]

    # --- Releases und Download-Zahlen ----------------------------------
    releases = api_all(f"/repos/{full}/releases", max_pages=3)
    rel_out, total_dl = [], 0
    for r in releases:
        assets = []
        for a in r.get("assets", []):
            assets.append({"name": a.get("name"), "downloads": a.get("download_count", 0)})
            total_dl += a.get("download_count", 0)
        rel_out.append(
            {
                "tag": r.get("tag_name"),
                "name": r.get("name"),
                "published_at": r.get("published_at"),
                "prerelease": r.get("prerelease", False),
                "assets": assets,
                "url": r.get("html_url"),
            }
        )
    snap["releases"] = rel_out
    snap["downloads_total"] = total_dl
    snap["latest_release"] = rel_out[0] if rel_out else None

    # --- Neue Stars mit Zeitstempel ------------------------------------
    cutoff = iso(now - timedelta(days=7))
    stars_recent, star_errors = recent_stars(full, cutoff)
    snap["errors"].extend(star_errors)
    snap["stars_last_7d"] = sorted(stars_recent, key=lambda x: x["at"] or "", reverse=True)

    # --- Neue Forks ----------------------------------------------------
    forks = api_all(f"/repos/{full}/forks", {"sort": "newest"}, max_pages=1)
    cutoff = iso(now - timedelta(days=7))
    snap["forks_last_7d"] = [
        {
            "user": (f.get("owner") or {}).get("login"),
            "at": f.get("created_at"),
            "url": f.get("html_url"),
        }
        for f in forks
        if (f.get("created_at") or "") >= cutoff
    ]

    # --- Traffic (braucht PAT mit Administration: read) ----------------
    views, verr = api(f"/repos/{full}/traffic/views", {"per": "day"}, allow_fail=True)
    clones, cerr = api(f"/repos/{full}/traffic/clones", {"per": "day"}, allow_fail=True)
    refs, _ = api(f"/repos/{full}/traffic/popular/referrers", allow_fail=True)
    paths, _ = api(f"/repos/{full}/traffic/popular/paths", allow_fail=True)

    if views:
        snap["views_14d"] = views.get("count", 0)
        snap["views_14d_unique"] = views.get("uniques", 0)
        snap["views_daily"] = views.get("views", [])
    else:
        snap["views_14d"] = None
        snap["errors"].append(f"traffic/views: {verr}")

    if clones:
        snap["clones_14d"] = clones.get("count", 0)
        snap["clones_14d_unique"] = clones.get("uniques", 0)
        snap["clones_daily"] = clones.get("clones", [])
    else:
        snap["clones_14d"] = None
        snap["errors"].append(f"traffic/clones: {cerr}")

    snap["referrers"] = refs if isinstance(refs, list) else []
    snap["top_paths"] = paths if isinstance(paths, list) else []

    return snap


def merge_history(repo, snap):
    """Haengt den Schnappschuss an die Historie an, ein Eintrag pro Tag."""
    path = os.path.join(DATA_DIR, f"{repo}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                doc = json.load(f)
            except json.JSONDecodeError:
                doc = {}
    else:
        doc = {}

    history = doc.get("history", [])
    # Nur die schlanken Kennzahlen wandern in die Historie
    slim = {
        "date": snap["date"],
        "collected_at": snap["collected_at"],
        "stars": snap.get("stars"),
        "forks": snap.get("forks"),
        "watchers": snap.get("watchers"),
        "open_issues_count": snap.get("open_issues_count"),
        "open_prs_count": snap.get("open_prs_count"),
        "downloads_total": snap.get("downloads_total"),
        "views_14d": snap.get("views_14d"),
        "views_14d_unique": snap.get("views_14d_unique"),
        "clones_14d": snap.get("clones_14d"),
        "latest_release": (snap.get("latest_release") or {}).get("tag"),
    }
    history = [h for h in history if h.get("date") != snap["date"]]
    history.append(slim)
    history.sort(key=lambda h: h.get("date", ""))
    history = history[-HISTORY_KEEP_DAYS:]

    doc["repo"] = snap["repo"]
    doc["current"] = snap
    doc["history"] = history

    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not TOKEN:
        print("WARNUNG: kein METRICS_TOKEN gesetzt, Traffic wird fehlen.", file=sys.stderr)

    index = {
        "generated_at": iso(datetime.now(timezone.utc)),
        "owner": OWNER,
        "repos": [],
        "token_present": bool(TOKEN),
    }

    for repo in REPOS:
        snap = collect_repo(repo)
        doc = merge_history(repo, snap)
        hist = doc["history"]
        prev = hist[-2] if len(hist) >= 2 else None

        def delta(key):
            if not prev or prev.get(key) is None or snap.get(key) is None:
                return None
            return snap[key] - prev[key]

        index["repos"].append(
            {
                "repo": snap["repo"],
                "name": repo,
                "stars": snap.get("stars"),
                "forks": snap.get("forks"),
                "watchers": snap.get("watchers"),
                "open_issues_count": snap.get("open_issues_count"),
                "open_prs_count": snap.get("open_prs_count"),
                "downloads_total": snap.get("downloads_total"),
                "views_14d": snap.get("views_14d"),
                "clones_14d": snap.get("clones_14d"),
                "latest_release": (snap.get("latest_release") or {}).get("tag"),
                "delta_vs_prev_day": {
                    "stars": delta("stars"),
                    "forks": delta("forks"),
                    "downloads_total": delta("downloads_total"),
                    "open_issues_count": delta("open_issues_count"),
                    "open_prs_count": delta("open_prs_count"),
                },
                "prev_date": prev.get("date") if prev else None,
                "errors": snap.get("errors", []),
            }
        )
        print(f"   stars={snap.get('stars')} dl={snap.get('downloads_total')} "
              f"views={snap.get('views_14d')} issues={snap.get('open_issues_count')} "
              f"prs={snap.get('open_prs_count')}")

    with open(os.path.join(DATA_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1, ensure_ascii=False)
    print("fertig")


if __name__ == "__main__":
    main()
