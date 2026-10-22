"""Canned job pages and a fake web, used ONLY by the tests and by backend/demo_import_server.py.

The real importer refuses localhost and private addresses, so a web page served from this computer cannot be
imported. For a repeatable demonstration this file provides a few hand-written pages under made-up host names
(careers.northwind-analytics.com and so on) and a fake network (httpx.MockTransport plus a fake DNS resolver) that
the importer can be pointed at. Nothing here is used by the production server, and nothing here contacts the internet.

The page contents are written for this project. They are not real job postings.
"""

import json

import httpx

PUBLIC_LOOKING_IP = "93.184.216.34"          # never contacted; it only has to look public to the safety check


def page(body, status=200, content_type="text/html; charset=utf-8", headers=None):
    data = body.encode() if isinstance(body, str) else body
    return httpx.Response(status, headers={"content-type": content_type, **(headers or {})}, stream=httpx.ByteStream(data))


def redirect(location, status=302):
    return httpx.Response(status, headers={"location": location}, stream=httpx.ByteStream(b""))


class DemoWeb:
    """A tiny fake internet: (host, path) -> response. Records every request for the tests."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        self.lookups = []

    def add(self, host, path, factory):
        self.routes[(host, path)] = factory
        return self

    def resolver(self, host, port):
        self.lookups.append(host)
        return [PUBLIC_LOOKING_IP]

    def handler(self, request):
        host = request.headers.get("host", "")
        self.requests.append({"host": host, "path": request.url.path, "connect_host": request.url.host})
        factory = self.routes.get((host, request.url.path))
        return factory() if factory else page("<html><body>Not found</body></html>", 404)

    def transport(self):
        return httpx.MockTransport(self.handler)


# ---------------------------------------------------------------------------------------------------------------
# Hand-written pages
# ---------------------------------------------------------------------------------------------------------------
_PROFESSIONAL_DESCRIPTION = (
    "<p>We are looking for a software engineer to join our platform team. You will design, build and test backend "
    "services in Python, review code with teammates, and participate in on-call rotation.</p>"
    "<h2>About Us</h2><p>Northwind Analytics is a data company serving hospitals and universities. We build tools "
    "that help researchers understand their data.</p>"
    "<h2>Requirements</h2><ul><li>Bachelor's degree in computer science or equivalent experience.</li>"
    "<li>3 years of Python and SQL.</li><li>Experience with automated testing and version control.</li></ul>"
    "<h2>Benefits</h2><p>Health, dental and vision insurance, 401(k) match, paid vacation.</p>")

PROFESSIONAL_JOB_HTML = (
    "<html><head><title>Software Engineer | Northwind Analytics Careers</title>"
    '<script type="application/ld+json">'
    + json.dumps({
        "@context": "https://schema.org", "@type": "JobPosting", "title": "Software Engineer",
        "description": _PROFESSIONAL_DESCRIPTION,
        "hiringOrganization": {"@type": "Organization", "name": "Northwind Analytics"},
        "employmentType": "FULL_TIME", "datePosted": "2026-10-12",
        "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Seattle",
                                                        "addressRegion": "WA", "addressCountry": "US"}},
    })
    + '</script></head><body><nav>Home | Careers | Contact</nav><h1>Software Engineer</h1>'
      '<p>See the full description in the structured data of this page.</p><footer>Northwind Analytics</footer></body></html>')

# A page of a recruiting platform without structured data (the visible text is used)
PLATFORM_JOB_HTML = """<html><head><title>Customer Support Representative - Northwind Analytics</title></head>
<body><header>Northwind Analytics - Open positions</header><main><h1>Customer Support Representative</h1>
<p>Remote, United States</p>
<h2>About the role</h2><p>Answer customer questions by email and chat, and help researchers use our software.
You will work with a friendly team and keep our help center up to date.</p>
<h2>Requirements</h2><ul><li>Good written English.</li><li>One year of customer service experience.</li></ul>
<h2>Benefits</h2><p>Health insurance, paid vacation and a yearly learning budget.</p></main>
<footer>Privacy policy</footer></body></html>"""

SUSPICIOUS_JOB_HTML = """<html><head><title>Work From Home - Earn $5000 Weekly!!!</title></head>
<body><main><h1>Work From Home - Earn $5000 Weekly!!!</h1>
<p>No experience needed! Earn thousands every week from home. Limited spots.</p>
<p>Send your full name, address, date of birth and bank account details to start immediately.
A small registration fee is required.</p>
<h2>Requirements</h2><p>Must have a bank account and be able to pay the registration fee.</p>
<p>Contact our hiring manager at quickhire.jobs@gmail.com</p></main></body></html>"""

JAVASCRIPT_ONLY_HTML = ('<html><head><title>Jobs</title></head><body><div id="root"></div>'
                        '<noscript>You need to enable JavaScript to run this app.</noscript>'
                        '<script src="/static/app.js"></script></body></html>')


def build_demo_web():
    """The fake internet used by the tests and by the demonstration server."""
    web = DemoWeb()
    # A company page with structured data, on the company's own domain
    web.add("careers.northwind-analytics.com", "/jobs/software-engineer", lambda: page(PROFESSIONAL_JOB_HTML))
    # A recruiting platform: the old address redirects inside the platform's own domain
    web.add("boards.greenhouse.io", "/northwind/jobs/4012345",
            lambda: redirect("https://job-boards.greenhouse.io/northwind/jobs/4012345", 301))
    web.add("job-boards.greenhouse.io", "/northwind/jobs/4012345", lambda: page(PLATFORM_JOB_HTML))
    # A link shortener that leads to a plain-HTTP page on an unrelated domain
    web.add("short.example-links.com", "/r/3fK9", lambda: redirect("http://quick-hire-jobs.com/apply/data-entry"))
    web.add("quick-hire-jobs.com", "/apply/data-entry", lambda: page(SUSPICIOUS_JOB_HTML))
    # Sites that do not allow automated access, and a page that needs JavaScript
    web.add("www.job-board-example.com", "/view/991", lambda: page("<html><body>Forbidden</body></html>", status=403))
    web.add("spa.job-board-example.org", "/jobs/55", lambda: page(JAVASCRIPT_ONLY_HTML))
    return web
