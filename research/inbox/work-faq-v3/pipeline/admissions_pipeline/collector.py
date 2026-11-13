"""Bounded, robots-aware public collection. Local bodies never go to GitHub."""
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

AGENT = "SOGHAdmissionResearch/0.4"


def official_url(url, hosts):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "https" or p.hostname not in hosts or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError("unapproved official URL")
    return p


class Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl, {self.host})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Page(HTMLParser):
    def __init__(self, text, url):
        super().__init__(convert_charrefs=True)
        self.url, self.text, self.links = url, [], []
        self.skip = 0
        self.anchor = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "a":
            self.anchor = [urllib.parse.urljoin(self.url, dict(attrs).get("href", "")), []]

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == "a" and self.anchor:
            self.links.append({"url": self.anchor[0], "label": " ".join(self.anchor[1]).strip()})
            self.anchor = None

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())
            if self.anchor:
                self.anchor[1].append(data.strip())


class Collector:
    def __init__(self, root, hosts, delay=2, max_bytes=20_000_000):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hosts, self.delay, self.limit = set(hosts), delay, max_bytes
        self.robots, self.last = {}, {}
        with sqlite3.connect(self.root / "collection.sqlite") as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations(
                id INTEGER PRIMARY KEY,url TEXT NOT NULL,sha256 TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,metadata_json TEXT NOT NULL)""")

    def _read(self, opener, url, limit):
        req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/pdf,text/html,text/plain"})
        with opener.open(req, timeout=30) as response:
            data = response.read(limit + 1)
            length=response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length)!=len(data)):
                raise ValueError('incomplete or invalid HTTP body length')
            if len(data) > limit:
                raise ValueError("response exceeds collection limit")
            encoding = response.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                data = decoder.decompress(data, limit + 1)
                if len(data) > limit or not decoder.eof:
                    raise ValueError("decoded response exceeds limit or is incomplete")
            elif encoding not in ("", "identity"):
                raise ValueError("unsupported transport encoding")
            return data, {"final_url": response.url, "content_type": response.headers.get("Content-Type", ""),
                          "transport_encoding": encoding, "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}

    def fetch(self, url):
        p = official_url(url, self.hosts)
        opener = urllib.request.build_opener(Redirect(p.hostname))
        if p.hostname not in self.robots:
            try:
                raw, _ = self._read(opener, f"https://{p.hostname}/robots.txt", 500000)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                raw = b""
            robot = urllib.robotparser.RobotFileParser()
            robot.parse(raw.decode("utf-8", errors="replace").splitlines())
            self.robots[p.hostname] = robot
            self.last[p.hostname] = time.monotonic()
        robot = self.robots[p.hostname]
        if not robot.can_fetch(AGENT, url):
            raise ValueError("robots disallows collection")
        delay = max(self.delay, robot.crawl_delay(AGENT) or 0)
        if delay > 60:
            raise ValueError("crawl delay requires a later run")
        time.sleep(max(0, delay - (time.monotonic() - self.last.get(p.hostname, 0))))
        try:
            raw, metadata = self._read(opener, url, self.limit)
        finally:
            self.last[p.hostname] = time.monotonic()
        sha = hashlib.sha256(raw).hexdigest()
        kind = "pdf" if raw.startswith(b"%PDF-") else "html"
        if kind == "html" and "html" not in metadata["content_type"].lower():
            raise ValueError("unsupported source content type")
        path = self.root / (sha + "." + kind)
        if not path.exists():
            tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            tmp.write_bytes(raw)
            os.replace(tmp, path)
        result = dict(metadata, url=url, sha256=sha, bytes=len(raw), kind=kind,
                      retrieved_at=datetime.now(timezone.utc).isoformat(), robots_checked=True,
                      local_path=str(path), publication_allowed=False)
        with sqlite3.connect(self.root / "collection.sqlite") as db:
            previous = db.execute("SELECT sha256 FROM observations WHERE url=? ORDER BY id DESC LIMIT 1", (url,)).fetchone()
            result["previous_sha256"] = previous[0] if previous else None
            result["observation"] = "baseline" if not previous else ("unchanged" if previous[0] == sha else "changed_requires_review")
            db.execute("INSERT INTO observations(url,sha256,retrieved_at,metadata_json) VALUES(?,?,?,?)",
                       (url, sha, result["retrieved_at"], json.dumps(result, ensure_ascii=False)))
        return result

    def inspect_html(self, record, terms):
        raw = Path(record["local_path"]).read_bytes()
        page = Page(raw.decode("utf-8", errors="replace"), record["url"])
        # A candidate is navigation evidence, never a verified admissions fact.
        return {"candidate_links": [x for x in page.links if any(t in x["label"] for t in terms)],
                "text": "\n".join(page.text), "requires_review": True}

    def write_snapshot(self, record, source_id, output, supersedes=()):
        """SourceSnapshot v1, agreed in Claude PR #23 / Issue #15. LOCAL ONLY."""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", source_id):
            raise ValueError("unsafe source id")
        raw = Path(record["local_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("stored body no longer matches collection hash")
        if record["kind"] == "pdf":
            import pymupdf
            if b'%%EOF' not in raw[-1024:]:raise ValueError('incomplete PDF trailer')
            with pymupdf.open(stream=raw, filetype="pdf") as doc:
                if doc.is_encrypted or doc.is_repaired or not len(doc):raise ValueError('damaged or unreadable PDF')
                pages = [page.get_text() for page in doc]
        else:
            pages = ["\n".join(Page(raw.decode("utf-8", errors="strict"), record["url"]).text)]
        snapshot = {"schema_version": 1, "source_id": source_id, "url": record["url"],
                    "sha256": record["sha256"], "retrieved_at": record["retrieved_at"][:10],
                    "pages": pages, "supersedes": list(supersedes), "edition_note": "Collected official source; scope review remains required"}
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        # Same bytes can move to another URL; retain both immutable observations.
        url_id=hashlib.sha256(record['url'].encode()).hexdigest()[:12]
        path = directory / (source_id + "-" + record["sha256"] + '-' + url_id + ".snapshot.json")
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if any(previous[k] != snapshot[k] for k in ("url", "sha256", "pages", "supersedes")):
                raise ValueError("immutable snapshot identity conflict")
        else:
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
        return path
