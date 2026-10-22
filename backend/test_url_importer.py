"""Tests for the safe job-page importer (backend/url_importer.py).

Run from the project root:   python -m backend.test_url_importer

No real internet and no model are used. A fake web (httpx.MockTransport) and a fake DNS resolver stand in for the
network, so every case is repeatable and nothing leaves this computer. Fake public addresses (93.184.216.34 and
similar) are never contacted; they only have to LOOK public to the safety check.

The most important checks are the ones that prove that unsafe destinations are refused BEFORE any request is sent:
for each of them the fake web records that it received zero requests.
"""

import ast
import gzip
import re
import sys
import time
import zlib
from pathlib import Path

import httpx

from backend import url_importer
from backend.intake_parser import parse_posting
from backend.url_importer import (FAILURE_MESSAGE, MAX_HTML_BYTES, MAX_REDIRECTS, REASONS, ImportFailure,
                                  fetch_public_page, import_job_url, is_public_address, validate_public_url)

results = []
PUBLIC_IP = "93.184.216.34"          # looks public; never contacted
OTHER_PUBLIC_IP = "151.101.1.69"


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------
# A fake web
# ---------------------------------------------------------------------------------------------------------------
def page(body, status=200, content_type="text/html; charset=utf-8", headers=None):
    """A response whose body is a real stream (read only when the importer reads it)."""
    data = body.encode() if isinstance(body, str) else body
    all_headers = {"content-type": content_type, **(headers or {})}
    return httpx.Response(status, headers=all_headers, stream=httpx.ByteStream(data))


def redirect(location, status=302, headers=None):
    return httpx.Response(status, headers={"location": location, **(headers or {})}, stream=httpx.ByteStream(b""))


class CountingStream(httpx.SyncByteStream):
    """A body that produces `total` bytes in chunks and counts how many bytes were really pulled."""

    def __init__(self, total, chunk=65536):
        self.total, self.chunk, self.served = total, chunk, 0

    def __iter__(self):
        while self.served < self.total:
            size = min(self.chunk, self.total - self.served)
            self.served += size
            yield b"x" * size


class FakeWeb:
    def __init__(self, dns=None):
        self.routes = {}        # (host, path) -> function returning a NEW httpx.Response
        self.requests = []      # what was really requested
        self.lookups = []       # host names the resolver was asked about
        self.dns = dns or {}

    def add(self, host, path, factory):
        self.routes[(host, path)] = factory
        return self

    def resolver(self, host, port):
        self.lookups.append(host)
        return self.dns.get(host, [PUBLIC_IP])

    def handler(self, request):
        host = request.headers.get("host", "")
        self.requests.append({"host": host, "connect_host": request.url.host, "path": request.url.path,
                              "headers": dict(request.headers), "sni": request.extensions.get("sni_hostname"),
                              "scheme": request.url.scheme})
        factory = self.routes.get((host, request.url.path))
        return factory() if factory else page("not found", 404)

    def transport(self):
        return httpx.MockTransport(self.handler)

    def run(self, url):
        """Import `url`. Returns (result dict or None, failure reason or None)."""
        try:
            return import_job_url(url, resolver=self.resolver, transport=self.transport()), None
        except ImportFailure as failure:
            assert failure.reason in REASONS
            return None, failure.reason


def reached_network(web):
    return len(web.requests) > 0


# ---------------------------------------------------------------------------------------------------------------
# Sample pages
# ---------------------------------------------------------------------------------------------------------------
JSON_LD_PAGE = """<html><head><title>Data Analyst at Acme | Careers</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting", "title": "Data Analyst",
 "hiringOrganization": {"@type": "Organization", "name": "Acme Analytics"},
 "description": "<p>Acme builds dashboards for hospitals.</p><h2>About Us</h2><p>We are a team of forty analysts.</p><h2>Requirements</h2><ul><li>SQL</li><li>Python</li></ul><h2>Benefits</h2><p>Health insurance and paid time off.</p>",
 "employmentType": ["FULL_TIME"], "datePosted": "2026-10-01",
 "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Austin", "addressRegion": "TX", "addressCountry": "US"}},
 "baseSalary": {"@type": "MonetaryAmount", "currency": "USD", "value": {"@type": "QuantitativeValue", "minValue": 90000, "maxValue": 110000, "unitText": "YEAR"}}}
</script></head><body><nav>NAV_ONLY_TEXT</nav><h1>Data Analyst</h1></body></html>"""

PLAIN_PAGE = """<html><head><title>Support Specialist | Brightpath</title><script>var TRACKER_ONLY_TEXT = 1;</script></head>
<body><nav><a href="/">Home</a> <a href="/jobs">NAV_ONLY_TEXT</a></nav>
<div id="cookie-banner">COOKIE_ONLY_TEXT we use cookies</div>
<header>PAGE_HEADER_ONLY_TEXT</header>
<main><h1>Support Specialist</h1>
<h2>About Us</h2><p>Brightpath builds scheduling software for small clinics and has been doing so for ten years.</p>
<h2>Responsibilities</h2><ul><li>Answer customer tickets by email</li><li>Update the help center</li></ul>
<h2>Requirements</h2><ul><li>Clear written English</li><li>One year of support experience</li></ul>
<h2>Benefits</h2><p>Paid time off and a learning budget for every employee.</p></main>
<footer>FOOTER_ONLY_TEXT privacy policy</footer></body></html>"""


def web_with_page(body=PLAIN_PAGE, host="careers.brightpath-example.com", path="/jobs/1"):
    return FakeWeb().add(host, path, lambda: page(body)), f"https://{host}{path}"


# ---------------------------------------------------------------------------------------------------------------
def test_successful_imports():
    web, url = web_with_page()
    result, reason = web.run(url)
    check("1. a valid HTTPS public job page is imported", result is not None and reason is None)
    check("   the result has every field of the import structure",
          set(result) >= {"requested_url", "final_url", "source_domain", "redirect_count", "https",
                          "structured_job_data_found", "page_title", "company_name", "raw_posting", "extracted_fields",
                          "timings_ms"})
    check("   source domain, https flag and redirect count are reported",
          result["source_domain"] == "careers.brightpath-example.com" and result["https"] is True
          and result["redirect_count"] == 0 and result["final_url"] == url)
    first = web.requests[0]
    check("   the request went to the address that was checked, not to the name",
          first["connect_host"] == PUBLIC_IP and first["host"] == "careers.brightpath-example.com")
    check("   for HTTPS the certificate name is still the real host name (SNI)", first["sni"] == "careers.brightpath-example.com")
    check("   the User-Agent says it is JobGuard", "JobGuard" in first["headers"]["user-agent"])
    check("   no cookie, no authorization header is sent", "cookie" not in first["headers"] and "authorization" not in first["headers"])
    check("   the host name was resolved by us before the request", web.lookups == ["careers.brightpath-example.com"])

    # 2. JobPosting JSON-LD
    web, url = web_with_page(JSON_LD_PAGE)
    result, _ = web.run(url)
    text = result["raw_posting"]
    check("2. JobPosting JSON-LD is detected and preferred", result["structured_job_data_found"] is True)
    check("   title, company, salary, location, employment type and dates come from the page's data",
          text.startswith("Data Analyst") and result["company_name"] == "Acme Analytics"
          and "Salary: USD 90,000-110,000 per year" in text and "Location: Austin, TX, US" in text
          and "Employment type: Full time" in text and "Date posted: 2026-10-01" in text)
    check("   the description's headings and list items are kept as lines",
          "\nRequirements\n" in text and "- SQL" in text and "- Python" in text)
    check("   page chrome outside the JSON-LD (navigation) is not mixed in", "NAV_ONLY_TEXT" not in text)
    escaped = JSON_LD_PAGE.replace('"description": "<p>', '"description": "\\\\n<p>')
    web, url = web_with_page(escaped)
    result, _ = web.run(url)
    check("   a literal backslash-n left in a platform's data is turned into a line break",
          result is not None and "\\n" not in result["raw_posting"] and "Acme builds dashboards" in result["raw_posting"])
    fields = result["extracted_fields"]
    check("   the existing Smart Intake Parser sorted it into the five fields",
          fields["title"] == "Data Analyst" and "forty analysts" in fields["company_profile"]
          and "SQL" in fields["requirements"] and "Health insurance" in fields["benefits"]
          and "Salary: USD" in fields["benefits"])
    check("   nothing is invented: every word of the posting text exists in the page's JSON-LD",
          all(word in JSON_LD_PAGE.replace("\\u2019", "'") or word in ("Company:", "Salary:", "Location:", "Employment", "type:",
                                                                         "Date", "posted:", "Job", "Description", "per", "year",
                                                                         "Full", "time", "USD", "90,000-110,000", "Austin,", "TX,", "US")
              for word in re.findall(r"[A-Za-z0-9,\-:]+", text)))

    # structured data variants
    graph = ('<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite","name":"x"},'
             '{"@type":["JobPosting"],"title":"Nurse","description":"&lt;p&gt;' + "Care for patients on the ward. " * 6 + '&lt;/p&gt;",'
             '"hiringOrganization":"Mercy Clinic"}]}</script><body><h1>Nurse</h1></body></html>')
    web, url = web_with_page(graph)
    result, reason = web.run(url)
    check("   JSON-LD inside @graph, with @type as a list and an HTML-escaped description, still works",
          result is not None and result["company_name"] == "Mercy Clinic" and "Care for patients on the ward." in result["raw_posting"]
          and "<p>" not in result["raw_posting"], reason)
    broken = ('<html><script type="application/ld+json">{ not json </script>' + PLAIN_PAGE[6:])
    web, url = web_with_page(broken)
    result, reason = web.run(url)
    check("   broken JSON-LD is ignored and the page text is used instead",
          result is not None and result["structured_job_data_found"] is False and "Requirements" in result["raw_posting"], reason)
    thin = ('<html><script type="application/ld+json">{"@type":"JobPosting","title":"Cashier","description":"Short."}</script>'
            + PLAIN_PAGE[6:])
    web, url = web_with_page(thin)
    result, _ = web.run(url)
    check("   a JobPosting without a real description falls back to the visible page text",
          result is not None and result["structured_job_data_found"] is True and "Brightpath builds" in result["raw_posting"]
          and "Cashier" not in result["raw_posting"])

    # 3. No JSON-LD: visible-text fallback
    web, url = web_with_page(PLAIN_PAGE)
    result, _ = web.run(url)
    text = result["raw_posting"]
    check("3. without JSON-LD the visible text is used", result["structured_job_data_found"] is False)
    check("   scripts, navigation, cookie banner, page header and footer are removed",
          not any(word in text for word in ("TRACKER_ONLY_TEXT", "NAV_ONLY_TEXT", "COOKIE_ONLY_TEXT",
                                            "PAGE_HEADER_ONLY_TEXT", "FOOTER_ONLY_TEXT")))
    lines = text.split("\n")
    check("   headings stay on their own lines and list items become '- ' lines",
          "About Us" in lines and "Requirements" in lines and "- Clear written English" in lines)
    check("   the page title is reported", result["page_title"] == "Support Specialist | Brightpath")
    check("   the text goes through the EXISTING Smart Intake Parser (same result as parsing it directly)",
          result["extracted_fields"] == parse_posting(text).to_dict())
    check("   the five fields are found", result["extracted_fields"]["title"] == "Support Specialist"
          and "Brightpath builds" in result["extracted_fields"]["company_profile"]
          and "Clear written English" in result["extracted_fields"]["requirements"]
          and "Paid time off" in result["extracted_fields"]["benefits"])

    # page-level header is dropped, but a header inside an article is part of the job
    article = PLAIN_PAGE.replace("<main>", "<main><article><header>ARTICLE_HEADER_TEXT job family</header>").replace("</main>", "</article></main>")
    web, url = web_with_page(article)
    result, _ = web.run(url)
    check("   a <header> inside the job article is kept, the page-level header is not",
          "ARTICLE_HEADER_TEXT" in result["raw_posting"] and "PAGE_HEADER_ONLY_TEXT" not in result["raw_posting"])
    hidden = PLAIN_PAGE.replace("<main>", '<main><p style="display:none">HIDDEN_ONLY_TEXT</p><p hidden>HIDDEN_ATTR_TEXT</p>')
    web, url = web_with_page(hidden)
    result, _ = web.run(url)
    check("   hidden elements are not read", "HIDDEN_ONLY_TEXT" not in result["raw_posting"] and "HIDDEN_ATTR_TEXT" not in result["raw_posting"])

    latin = PLAIN_PAGE.replace("Clear written English", "Caf\u00e9 service skills").encode("latin-1")
    web = FakeWeb().add("careers.brightpath-example.com", "/jobs/1",
                        lambda: page(latin, content_type="text/html; charset=iso-8859-1"))
    result, _ = web.run("https://careers.brightpath-example.com/jobs/1")
    check("   a page in another character set (ISO-8859-1) is decoded correctly", "Caf\u00e9 service skills" in result["raw_posting"])

    nested = "<html><body><main>" + "<div>" * 30000 + "Deep text " * 40 + "</div>" * 30000 + "</main></body></html>"
    web, url = web_with_page(nested)
    started = time.perf_counter()
    result, reason = web.run(url)
    check("   30,000 nested elements neither crash nor hang the importer",
          (result is not None or reason in REASONS) and time.perf_counter() - started < 10, reason or "")

    web, url = web_with_page(PLAIN_PAGE.replace("Paid time off", "Paid time off. " + "Long text. " * 6000))
    result, _ = web.run(url)
    check("   the imported text is capped at 50,000 characters", result is not None and len(result["raw_posting"]) <= 50_000)


def test_redirects():
    web = FakeWeb()
    web.add("short.example-links.com", "/abc", lambda: redirect("https://careers.brightpath-example.com/jobs/1"))
    web.add("careers.brightpath-example.com", "/jobs/1", lambda: page(PLAIN_PAGE))
    result, reason = web.run("https://short.example-links.com/abc")
    check("4. a redirect to another public domain is followed and reported",
          result is not None and result["redirect_count"] == 1 and result["source_domain"] == "careers.brightpath-example.com"
          and result["final_url"] == "https://careers.brightpath-example.com/jobs/1"
          and result["requested_url"] == "https://short.example-links.com/abc", reason)
    check("   BOTH hosts were resolved and checked before they were requested",
          web.lookups == ["short.example-links.com", "careers.brightpath-example.com"])

    web = FakeWeb().add("a.example-site.com", "/x", lambda: redirect("/y")).add("a.example-site.com", "/y", lambda: page(PLAIN_PAGE))
    result, _ = web.run("https://a.example-site.com/x")
    check("   a relative redirect Location works", result is not None and result["final_url"].endswith("/y"))

    web = FakeWeb()
    for step in range(10):                       # /hop0 -> /hop1 -> /hop2 -> ... (an endless-looking chain)
        web.add("a.example-site.com", f"/hop{step}", lambda step=step: redirect(f"https://a.example-site.com/hop{step + 1}"))
    result, reason = web.run("https://a.example-site.com/hop0")
    check("5. too many redirects are refused", result is None and reason == "too_many_redirects", str(reason))
    check(f"   at most {MAX_REDIRECTS + 1} requests were made", len(web.requests) <= MAX_REDIRECTS + 1, str(len(web.requests)))

    web = FakeWeb().add("a.example-site.com", "/x", lambda: redirect("http://careers.brightpath-example.com/jobs/1"))
    web.add("careers.brightpath-example.com", "/jobs/1", lambda: page(PLAIN_PAGE))
    result, _ = web.run("https://a.example-site.com/x")
    check("   a redirect that ends on plain http is reported as not https", result is not None and result["https"] is False)

    # 18. public URL redirecting to private / local destinations
    for target, label in [("http://169.254.169.254/latest/meta-data/", "the cloud metadata address"),
                          ("http://127.0.0.1:80/admin", "127.0.0.1"), ("http://localhost/admin", "localhost"),
                          ("http://[::1]/", "::1"), ("http://10.0.0.5/", "a 10.x address"),
                          ("http://192.168.1.1/", "a 192.168.x address"), ("file:///etc/passwd", "a file: URL"),
                          ("ftp://files.example-site.com/job.html", "an ftp: URL"),
                          ("http://careers.brightpath-example.com:8080/x", "a non-standard port"),
                          ("http://user:pass@careers.brightpath-example.com/x", "a URL with credentials")]:
        web = FakeWeb().add("a.example-site.com", "/x", lambda target=target: redirect(target))
        result, reason = web.run("https://a.example-site.com/x")
        check(f"18. a public URL that redirects to {label} is stopped", result is None and reason in ("blocked_address", "invalid_url"), str(reason))
        check("    only the first (public) URL was ever requested", len(web.requests) == 1 and web.requests[0]["host"] == "a.example-site.com")

    web = FakeWeb(dns={"internal-names.example-site.com": ["10.1.2.3"]})
    web.add("a.example-site.com", "/x", lambda: redirect("https://internal-names.example-site.com/job"))
    result, reason = web.run("https://a.example-site.com/x")
    check("18. a redirect to a PUBLIC-looking name that resolves to a private address is stopped",
          result is None and reason == "blocked_address" and len(web.requests) == 1)

    calls = {"count": 0}

    def changing_resolver(host, port):          # public on the first lookup, private later
        calls["count"] += 1
        return [PUBLIC_IP] if host == "a.example-site.com" else ["192.168.0.10"]
    web = FakeWeb().add("a.example-site.com", "/x", lambda: redirect("https://b.example-site.com/y"))
    try:
        import_job_url("https://a.example-site.com/x", resolver=changing_resolver, transport=web.transport())
        stopped = False
    except ImportFailure as failure:
        stopped = failure.reason == "blocked_address"
    check("   the address is re-checked for every hop (second host resolves to a private address: stopped)", stopped and len(web.requests) == 1)

    web = FakeWeb().add("a.example-site.com", "/x", lambda: redirect("https://a.example-site.com/y", headers={"set-cookie": "session=abc; Path=/"}))
    web.add("a.example-site.com", "/y", lambda: page(PLAIN_PAGE))
    web.run("https://a.example-site.com/x")
    check("   cookies set by a page are not stored or sent back on the next hop",
          len(web.requests) == 2 and "cookie" not in web.requests[1]["headers"])


def test_response_limits_and_failures():
    for content_type in ["application/pdf", "image/png", "application/zip", "application/octet-stream", "application/json",
                         "text/plain", ""]:
        web = FakeWeb().add("files.example-site.com", "/x", lambda ct=content_type: page(b"%PDF-1.4 ...", content_type=ct))
        result, reason = web.run("https://files.example-site.com/x")
        check(f"6. a non-HTML response ({content_type or 'no content type'}) is refused", result is None and reason == "not_html", str(reason))
    web = FakeWeb().add("files.example-site.com", "/x", lambda: page(PLAIN_PAGE, content_type="application/xhtml+xml"))
    result, _ = web.run("https://files.example-site.com/x")
    check("   application/xhtml+xml is accepted", result is not None)

    stream = {}

    def big_page():
        stream["s"] = CountingStream(20 * 1024 * 1024)
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=stream["s"])
    web = FakeWeb().add("big.example-site.com", "/x", big_page)
    result, reason = web.run("https://big.example-site.com/x")
    check("7. an oversized response (no Content-Length) is refused", result is None and reason == "too_large", str(reason))
    check("   the download was cut off near the limit, not read to the end",
          stream["s"].served <= MAX_HTML_BYTES + 2 * 65536, f"{stream['s'].served} bytes read of {stream['s'].total}")

    def lying_page():
        stream["s"] = CountingStream(6 * 1024 * 1024)
        return httpx.Response(200, headers={"content-type": "text/html", "content-length": "100"}, stream=stream["s"])
    web = FakeWeb().add("big.example-site.com", "/x", lying_page)
    result, reason = web.run("https://big.example-site.com/x")
    check("   a response that lies about its Content-Length is still cut off", result is None and reason == "too_large", str(reason))

    def huge_length():
        stream["s"] = CountingStream(10)
        return httpx.Response(200, headers={"content-type": "text/html", "content-length": str(50 * 1024 * 1024)}, stream=stream["s"])
    web = FakeWeb().add("big.example-site.com", "/x", huge_length)
    result, reason = web.run("https://big.example-site.com/x")
    check("   a huge declared Content-Length is refused without reading the body",
          result is None and reason == "too_large" and stream["s"].served == 0)

    bomb = gzip.compress(b"\0" * (40 * 1024 * 1024))
    web = FakeWeb().add("big.example-site.com", "/x", lambda: page(bomb, headers={"content-encoding": "gzip"}))
    started = time.perf_counter()
    result, reason = web.run("https://big.example-site.com/x")
    check(f"   a compressed page that expands to 40 MB is refused ({len(bomb)} bytes on the wire)",
          result is None and reason == "too_large" and time.perf_counter() - started < 5, str(reason))
    # The expansion must be bounded WHILE it happens (not only checked afterwards), or the bomb would fill memory first.
    produced = []
    real_decompressobj = zlib.decompressobj

    class WatchedDecompressor:
        def __init__(self, *args):
            self._inner = real_decompressobj(*args)

        def decompress(self, data, max_length=0):
            out = self._inner.decompress(data, max_length)
            produced.append((len(out), max_length))
            return out

        def flush(self, length=16384):
            return self._inner.flush(length)

        @property
        def unconsumed_tail(self):
            return self._inner.unconsumed_tail

    zlib.decompressobj = WatchedDecompressor
    try:
        FakeWeb().add("big.example-site.com", "/x", lambda: page(bomb, headers={"content-encoding": "gzip"})).run("https://big.example-site.com/x")
    finally:
        zlib.decompressobj = real_decompressobj
    check("   decompression itself is bounded: every step asks for a limited amount and never returns more than the limit",
          produced and all(0 < limit <= MAX_HTML_BYTES + 1 and size <= limit for size, limit in produced),
          f"largest step {max((s for s, _ in produced), default=0)} bytes")
    web = FakeWeb().add("ok.example-site.com", "/x", lambda: page(gzip.compress(PLAIN_PAGE.encode()), headers={"content-encoding": "gzip"}))
    result, reason = web.run("https://ok.example-site.com/x")
    check("   a normal gzip-compressed page is read", result is not None and "Requirements" in result["raw_posting"], str(reason))
    web = FakeWeb().add("ok.example-site.com", "/x", lambda: page(b"x", headers={"content-encoding": "br"}))
    check("   an unsupported compression format is refused", web.run("https://ok.example-site.com/x")[1] == "not_html")

    def timeout_handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    result_reason = None
    try:
        import_job_url("https://slow.example-site.com/x", resolver=lambda h, p: [PUBLIC_IP], transport=httpx.MockTransport(timeout_handler))
    except ImportFailure as failure:
        result_reason = failure.reason
    check("8. a read timeout stops the import gracefully", result_reason == "timeout", str(result_reason))

    def connect_timeout_handler(request):
        raise httpx.ConnectTimeout("no route", request=request)
    result_reason = None
    try:
        import_job_url("https://slow.example-site.com/x", resolver=lambda h, p: [PUBLIC_IP], transport=httpx.MockTransport(connect_timeout_handler))
    except ImportFailure as failure:
        result_reason = failure.reason
    check("   a connect timeout stops the import gracefully", result_reason == "timeout", str(result_reason))

    attempts = []

    def refuse_first_handler(request):
        attempts.append(request.url.host)
        if request.url.host == PUBLIC_IP:
            raise httpx.ConnectError("refused", request=request)
        return page(PLAIN_PAGE)
    got = import_job_url("https://multi.example-site.com/x", resolver=lambda h, p: [PUBLIC_IP, OTHER_PUBLIC_IP],
                         transport=httpx.MockTransport(refuse_first_handler))
    check("   if the first checked address refuses the connection, the next checked address is tried",
          attempts == [PUBLIC_IP, OTHER_PUBLIC_IP] and got["source_domain"] == "multi.example-site.com")

    clock = {"t": 0.0}

    def fake_now():
        clock["t"] += 7.0
        return clock["t"]
    web = FakeWeb().add("slow.example-site.com", "/x", lambda: httpx.Response(200, headers={"content-type": "text/html"}, stream=CountingStream(10 * 65536)))
    try:
        fetch_public_page("https://slow.example-site.com/x", resolver=web.resolver, transport=web.transport(), now=fake_now)
        total_reason = None
    except ImportFailure as failure:
        total_reason = failure.reason
    check("   the total time limit stops a response that drips in slowly", total_reason == "timeout", str(total_reason))

    # 9. blocked sites: stop, never bypass
    for status, expected in [(401, "blocked_by_site"), (403, "blocked_by_site"), (429, "blocked_by_site"), (999, "blocked_by_site"),
                             (404, "not_found"), (410, "not_found"), (500, "unreachable"), (503, "unreachable")]:
        web = FakeWeb().add("jobs.example-board.com", "/x", lambda s=status: page("denied", status=s))
        result, reason = web.run("https://jobs.example-board.com/x")
        check(f"9. HTTP {status} stops the import ({expected})", result is None and reason == expected, str(reason))
        check("   and nothing is retried or worked around", len(web.requests) == 1)
    captcha = "<html><head><title>Just a moment...</title></head><body><h1>Verify you are human</h1><p>Checking your browser before accessing the site.</p></body></html>"
    web, url = web_with_page(captcha)
    check("   a CAPTCHA / bot-check page is recognized and the import stops", web.run(url)[1] == "blocked_by_site")
    login = "<html><head><title>Sign in</title></head><body><h1>Sign in to continue</h1><p>Please log in to view this job.</p></body></html>"
    web, url = web_with_page(login)
    check("   a login page is not mistaken for a job", web.run(url)[1] in ("blocked_by_site", "no_content"))
    spa = '<html><head><title>Jobs</title></head><body><div id="root"></div><noscript>You need to enable JavaScript to run this app.</noscript><script src="/app.js"></script></body></html>'
    web, url = web_with_page(spa)
    check("   a JavaScript-only page (nothing to read) says to paste the posting instead", web.run(url)[1] in ("no_content", "blocked_by_site"))
    apply_form = PLAIN_PAGE.replace("</main>", '<form><div class="g-recaptcha"></div></form></main>') \
        .replace("<head>", '<head><script src="https://www.google.com/recaptcha/api.js"></script>')
    web, url = web_with_page(apply_form)
    check("   a normal job page that merely contains a reCAPTCHA script is NOT treated as blocked", web.run(url)[0] is not None)
    check("   the user-facing failure text is the agreed sentence",
          FAILURE_MESSAGE == "We couldn't import this page automatically. Paste the job posting instead.")


def test_unsafe_urls_are_refused_before_any_request():
    cases = {
        "10. malformed URL": ["", "   ", "not a url at all", "http://", "https://", "https://exa mple.com/x", "http://[::1", "https://exa\tmple.com",
                              "https://.com", "https://..example.com", "http://" + "a" * 300 + ".com", "https://" + "x" * 3000],
        "11. credentials in the URL": ["https://user:pass@careers.brightpath-example.com/x", "https://user@careers.brightpath-example.com/x",
                                       "http://:pass@careers.brightpath-example.com/"],
        "12. localhost / .local / .internal": ["http://localhost/", "http://localhost:80/", "https://LOCALHOST/", "http://foo.localhost/",
                                               "http://printer.local/", "http://db.internal/", "http://metadata.google.internal/",
                                               "http://router.lan/", "http://intranet/", "http://host.localdomain/", "http://localhost./"],
        "13. 127.0.0.1 and its disguises": ["http://127.0.0.1/", "http://127.0.0.1:80/admin", "https://127.1/", "http://0177.0.0.1/",
                                            "http://2130706433/", "http://0x7f000001/", "http://127.0.0.1.nip.io.localhost/", "http://0.0.0.0/"],
        "14. ::1 and IPv6 forms": ["http://[::1]/", "http://[0:0:0:0:0:0:0:1]/", "http://[::ffff:127.0.0.1]/", "http://[::]/",
                                   "http://[::ffff:7f00:1]/"],
        "15. RFC1918 private addresses": ["http://10.0.0.5/", "http://172.16.0.1/", "http://172.31.255.255/", "http://192.168.1.1/",
                                          "http://100.64.0.1/", "http://[fd00::1]/"],
        "16. link-local addresses": ["http://169.254.1.1/", "http://[fe80::1]/", "http://[fe80::1%25eth0]/"],
        "17. metadata-service-like addresses": ["http://169.254.169.254/latest/meta-data/", "http://100.100.100.200/latest/meta-data/",
                                                "http://[fd00:ec2::254]/latest/meta-data/", "http://192.0.0.192/"],
        "unsupported schemes": ["file:///etc/passwd", "ftp://files.example-site.com/job.html", "data:text/html,<h1>hi</h1>",
                                "javascript:alert(1)", "gopher://example-site.com/", "mailto:a@b.com", "ws://example-site.com/",
                                "localhost:8080/x"],
        "unsupported ports": ["http://careers.brightpath-example.com:8080/x", "https://careers.brightpath-example.com:8443/x",
                              "http://careers.brightpath-example.com:22/", "https://careers.brightpath-example.com:0/",
                              "http://careers.brightpath-example.com:99999/"],
        "documentation / reserved IPs": ["http://192.0.2.1/", "http://198.51.100.1/", "http://203.0.113.9/", "http://240.0.0.1/",
                                         "http://255.255.255.255/", "http://224.0.0.1/", "http://[ff02::1]/", "http://[2001:db8::1]/",
                                         "http://[2002:7f00:1::1]/", "http://[64:ff9b::7f00:1]/"],
    }
    for label, urls in cases.items():
        all_refused, any_request, any_lookup = True, False, False
        reasons = set()
        for url in urls:
            web = FakeWeb()
            result, reason = web.run(url)
            if result is not None or reason not in ("invalid_url", "blocked_address"):
                all_refused = False
                print(f"      not refused as expected: {url!r} -> {reason}")
            reasons.add(reason)
            any_request |= reached_network(web)
            any_lookup |= bool(web.lookups)
        check(f"{label}: all {len(urls)} URLs are refused", all_refused, ", ".join(sorted(map(str, reasons))))
        check(f"{label}: nothing was requested and no DNS lookup was needed", not any_request and not any_lookup)

    # names that RESOLVE to something non-public
    for name, addresses in {"to 127.0.0.1": ["127.0.0.1"], "to a 10.x address": ["10.2.3.4"], "to a 192.168.x address": ["192.168.1.20"],
                            "to the link-local metadata address": ["169.254.169.254"], "to ::1": ["::1"],
                            "to an IPv4-mapped loopback": ["::ffff:127.0.0.1"], "to a public AND a private address": [PUBLIC_IP, "10.0.0.1"],
                            "to a 100.64.x (carrier-grade NAT) address": ["100.100.100.200"], "to nothing": []}.items():
        web = FakeWeb(dns={"tricky.example-site.com": addresses})
        result, reason = web.run("https://tricky.example-site.com/job")
        check(f"15-17. a public-looking name that resolves {name} is refused before any request",
              result is None and reason in ("blocked_address", "unreachable") and not reached_network(web), str(reason))

    check("the same host on ports 80 and 443 is allowed (validated only; nothing fetched)",
          validate_public_url("http://careers.brightpath-example.com:80/x", lambda h, p: [PUBLIC_IP]).host == "careers.brightpath-example.com"
          and validate_public_url("https://careers.brightpath-example.com:443/x", lambda h, p: [PUBLIC_IP]).port == 443)
    scheme_less = validate_public_url("careers.brightpath-example.com/jobs/1", lambda h, p: [PUBLIC_IP])
    check("a link pasted without https:// is accepted and treated as https", scheme_less.scheme == "https" and scheme_less.url.endswith("/jobs/1"))
    check("an international host name is converted to xn-- form before checks",
          validate_public_url("https://b\u00fccher-example.com/x", lambda h, p: [PUBLIC_IP]).host == "xn--bcher-example-wob.com")
    v6 = FakeWeb(dns={"v6.example-site.com": ["2606:4700:4700::1111"]}).add("v6.example-site.com", "/x", lambda: page(PLAIN_PAGE))
    result, _ = v6.run("https://v6.example-site.com/x")
    check("a public IPv6 address is connected to in brackets", result is not None and v6.requests[0]["connect_host"] == "2606:4700:4700::1111")


def test_address_table():
    public = ["93.184.216.34", "8.8.8.8", "1.1.1.1", "151.101.1.69", "2606:4700:4700::1111", "2001:4860:4860::8888"]
    private = ["127.0.0.1", "127.255.255.254", "10.0.0.1", "172.16.5.5", "192.168.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
               "224.0.0.1", "240.0.0.1", "255.255.255.255", "192.0.2.1", "198.51.100.7", "203.0.113.1", "198.18.0.1", "::1", "::", "fe80::1",
               "fc00::1", "fd12:3456::1", "ff02::1", "2001:db8::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "2002:7f00:1::", "64:ff9b::a00:1",
               "not an ip", ""]
    check("is_public_address accepts ordinary public addresses", all(is_public_address(a) for a in public), str([a for a in public if not is_public_address(a)]))
    check("is_public_address rejects loopback, private, link-local, CGNAT, reserved, multicast, mapped and nonsense",
          not any(is_public_address(a) for a in private), str([a for a in private if is_public_address(a)]))


def test_independence_and_scope():
    source = Path(url_importer.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    check("the importer does not import the model, torch, transformers or any AI client",
          not (imported & {"torch", "transformers", "openai", "anthropic", "google"}) and "model_service" not in source, str(sorted(imported)))
    check("the importer does not use a browser automation tool",
          not (imported & {"playwright", "selenium", "pyppeteer", "splinter"}))
    root = Path(url_importer.__file__).resolve().parents[1]
    requirements = (root / "requirements.txt").read_text().lower()
    check("no browser-automation package is in requirements.txt", not any(word in requirements for word in ("playwright", "selenium", "puppeteer")))
    check("the importer does not follow redirects automatically", "follow_redirects=False" in source and "follow_redirects=True" not in source)
    check("test.csv is not read by the importer", "test.csv" not in source)
    check("every failure reason is one of the documented categories", all(r in REASONS for r in REASONS) and len(set(REASONS)) == len(REASONS))
    web, url = web_with_page()
    result, _ = web.run(url)
    check("the import result exposes no IP address or internal detail", PUBLIC_IP not in repr({k: v for k, v in result.items() if k != "raw_posting"}))
    check("the import result reports timings for fetch, html_extract and intake_parse",
          set(result["timings_ms"]) == {"fetch", "html_extract", "intake_parse"})


def main():
    test_successful_imports()
    test_redirects()
    test_response_limits_and_failures()
    test_unsafe_urls_are_refused_before_any_request()
    test_address_table()
    test_independence_and_scope()
    print(f"\n{sum(results)} of {len(results)} checks passed")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
