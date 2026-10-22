"""Safe import of ONE public job page (Milestone 14).

    job URL  ->  safety checks  ->  public HTML page  ->  readable job text  ->  (existing) Smart Intake Parser

Why this file is careful: the URL comes from a stranger on the internet and our server makes the request. A bad URL
could try to make the server talk to things only the server can reach (localhost, the home or office network, a
cloud "metadata" address). That attack is called SSRF. The protections are:

  * only http and https, only ports 80 and 443, no user:password@ in the URL
  * names like localhost / *.local / *.internal and raw IP-address hosts are refused
  * the host name is resolved by US and EVERY address must be public. If one is private, loopback, link-local,
    reserved, multicast or otherwise not public, the request is refused before anything is sent
  * the request goes to the IP address we just checked (not to the name again), so the name cannot change its
    answer between the check and the request (DNS rebinding). HTTPS still verifies the certificate for the name
  * redirects are followed by hand, at most MAX_REDIRECTS, and EVERY redirect target runs through all the checks
    again, so "public site -> redirect to http://169.254.169.254/" is stopped
  * timeouts, a total time limit, a 2 MB download limit (also for compressed pages), HTML content types only,
    no cookies, no login, no proxy, no JavaScript browser

If a site answers 401 / 403 / 429, shows a CAPTCHA or an "are you a robot" page, or needs JavaScript, the import
simply stops. Nothing here tries to get around access controls. The product then says "paste the posting instead".

Nothing is stored: the page, the URL and the text only exist while the request is running.
"""

import html
import http.cookiejar
import ipaddress
import json
import re
import socket
import time
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from backend.intake_parser import parse_posting

# ---------------------------------------------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------------------------------------------
MAX_URL_CHARS = 2048
MAX_REDIRECTS = 4                       # a few hops (http->https, www, tracking link) are normal; more is suspicious
MAX_HTML_BYTES = 2 * 1024 * 1024        # about 2 MB, counted AFTER decompression
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 8.0
TOTAL_TIMEOUT = 20.0                    # the whole import, all redirects included
ALLOWED_PORTS = (80, 443)
MAX_ADDRESSES_TRIED = 3
MAX_POSTING_CHARS = 50_000              # same limit as the /predict API
MIN_POSTING_CHARS = 200                 # less visible text than this is a JavaScript-only or login page
MIN_STRUCTURED_DESCRIPTION_CHARS = 80

USER_AGENT = ("JobGuardBot/1.0 (educational student project; fetches only the one public job page a user submits; "
              "no crawling)")
ACCEPTED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

# Names that never belong to the public internet
_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".localdomain", ".lan", ".home.arpa", ".intranet",
                          ".corp", ".home", ".private")

# Not public even if Python's own check were to call them "global" (they can embed or tunnel to private IPv4 hosts)
_BLOCKED_IPV6_PREFIXES = tuple(ipaddress.ip_network(p) for p in
                               ("2002::/16", "2001::/32", "64:ff9b::/96", "64:ff9b:1::/48"))

# ---------------------------------------------------------------------------------------------------------------
# What went wrong, in words that are safe to show. The details stay in the server log.
# ---------------------------------------------------------------------------------------------------------------
FAILURE_MESSAGE = "We couldn't import this page automatically. Paste the job posting instead."

REASONS = ("invalid_url", "blocked_address", "blocked_by_site", "not_found", "not_html", "too_large", "timeout",
           "too_many_redirects", "unreachable", "no_content")


class ImportFailure(Exception):
    """The page could not be imported. `reason` is one of REASONS; `detail` is for the server log only."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}")
        assert reason in REASONS, reason
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------------------------------------------
# Part 1: deciding whether a URL may be fetched
# ---------------------------------------------------------------------------------------------------------------
def is_public_address(address):
    """True only for ordinary, publicly routable IP addresses."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:           # ::ffff:127.0.0.1 is really 127.0.0.1
            ip = ip.ipv4_mapped
        elif any(ip in prefix for prefix in _BLOCKED_IPV6_PREFIXES):
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_loopback and not ip.is_link_local and not ip.is_private \
        and not ip.is_reserved and not ip.is_unspecified


def _system_resolver(host, port):
    """Ask the operating system for every address of a host name."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as error:
        raise ImportFailure("unreachable", f"DNS lookup failed: {error}")
    addresses = []
    for info in infos:
        address = info[4][0].split("%", 1)[0]
        if address not in addresses:
            addresses.append(address)
    return addresses


@dataclass
class SafeTarget:
    """A URL that passed every check, with the address we checked and will connect to."""

    url: str                  # the cleaned URL (no fragment)
    scheme: str
    host: str                 # ASCII (punycode) host name
    port: int | None          # only when the URL wrote one
    addresses: list           # public IP addresses of the host

    @property
    def effective_port(self):
        return self.port or (443 if self.scheme == "https" else 80)


def validate_public_url(url, resolver=None):
    """Run every safety check on one URL. Returns a SafeTarget or raises ImportFailure. No request is made here
    (only a DNS lookup)."""
    if not isinstance(url, str):
        raise ImportFailure("invalid_url", "not a string")
    url = url.strip()
    if not url or len(url) > MAX_URL_CHARS or any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
        raise ImportFailure("invalid_url", "empty, too long, or contains spaces/control characters")

    # A user may paste "company.com/careers/x" without the scheme. Anything that already has a scheme
    # ("javascript:", "data:", "file:", "ftp://", "localhost:8080") is judged as written.
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", url):
        url = "https://" + url.lstrip("/")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ImportFailure("invalid_url", "unparseable URL or port")

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ImportFailure("invalid_url", f"scheme {scheme!r} is not allowed")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise ImportFailure("invalid_url", "URL contains credentials")
    if port is not None and port not in ALLOWED_PORTS:
        raise ImportFailure("blocked_address", f"port {port} is not allowed")

    raw_host = (parts.hostname or "").strip().rstrip(".")
    if not raw_host:
        raise ImportFailure("invalid_url", "no host name")
    try:
        host = raw_host.lower().encode("idna").decode("ascii")      # Unicode names become xn-- names
    except (UnicodeError, ValueError):
        raise ImportFailure("invalid_url", "host name cannot be encoded")
    if len(host) > 253 or not re.fullmatch(r"[a-z0-9_.\-]+", host) or ".." in host or host.startswith("."):
        raise ImportFailure("invalid_url", "host name has unusual characters")

    # Raw IP addresses (127.0.0.1, ::1, 169.254.169.254, 10.0.0.5, 2130706433, 0x7f000001 ...) are never imported.
    try:
        ipaddress.ip_address(host)
        raise ImportFailure("blocked_address", "IP-address host")
    except ValueError:
        pass
    top_label = host.rsplit(".", 1)[-1]
    if "." not in host or top_label.isdigit() or top_label.startswith("0x"):
        raise ImportFailure("blocked_address", "single-label or number-like host")
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ImportFailure("blocked_address", "local host name")

    # Resolve it ourselves and require EVERY address to be public.
    resolve = resolver or _system_resolver
    addresses = list(resolve(host, port or (443 if scheme == "https" else 80)))
    if not addresses:
        raise ImportFailure("unreachable", "host did not resolve")
    for address in addresses:
        if not is_public_address(address):
            raise ImportFailure("blocked_address", "host resolves to a non-public address")

    clean = urlunsplit((scheme, parts.netloc.rsplit("@", 1)[-1], parts.path or "/", parts.query, ""))
    return SafeTarget(url=clean, scheme=scheme, host=host, port=port, addresses=addresses)


# ---------------------------------------------------------------------------------------------------------------
# Part 2: fetching (manual redirects, size limit, no cookies)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class FetchedPage:
    requested_url: str
    final_url: str
    redirect_count: int
    body: bytes
    charset: str | None


def _connect_url(target, address):
    """The URL that is really requested: the checked IP address instead of the name."""
    ip_part = f"[{address}]" if ":" in address else address
    netloc = ip_part + (f":{target.port}" if target.port else "")
    parts = urlsplit(target.url)
    return urlunsplit((target.scheme, netloc, parts.path or "/", parts.query, ""))


def _host_header(target):
    default = 443 if target.scheme == "https" else 80
    return target.host if target.port in (None, default) else f"{target.host}:{target.port}"


def _make_client(transport):
    client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=False,      # redirects are followed by hand, with every check repeated
        trust_env=False,             # ignore proxy environment variables
        http2=False,
    )
    # "No stored cookies": a policy that accepts cookies from no domain at all
    client.cookies.jar.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
    return client


def _read_limited_body(response, deadline, now):
    """Read the body, never holding more than MAX_HTML_BYTES, and never trusting Content-Length alone."""
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding in ("", "identity"):
        decoder = None
    elif encoding in ("gzip", "x-gzip"):
        decoder = zlib.decompressobj(zlib.MAX_WBITS | 16)
    elif encoding == "deflate":
        decoder = zlib.decompressobj(zlib.MAX_WBITS)
    else:
        raise ImportFailure("not_html", f"unsupported content-encoding {encoding!r}")

    body = bytearray()
    raw_total = 0
    try:
        for chunk in response.iter_raw():
            if now() > deadline:
                raise ImportFailure("timeout", "total time limit reached while downloading")
            raw_total += len(chunk)
            if raw_total > MAX_HTML_BYTES:
                raise ImportFailure("too_large", "download limit exceeded")
            if decoder is None:
                body += chunk
            else:
                pending = chunk
                while pending:               # a small compressed chunk can expand a lot: decode in bounded pieces
                    room = MAX_HTML_BYTES + 1 - len(body)
                    if room <= 0:
                        raise ImportFailure("too_large", "decompressed size limit exceeded")
                    body += decoder.decompress(pending, room)
                    pending = decoder.unconsumed_tail
            if len(body) > MAX_HTML_BYTES:
                raise ImportFailure("too_large", "size limit exceeded")
        if decoder is not None:
            body += decoder.flush(max(1, MAX_HTML_BYTES + 1 - len(body)))
            if len(body) > MAX_HTML_BYTES:
                raise ImportFailure("too_large", "decompressed size limit exceeded")
    except zlib.error:
        raise ImportFailure("not_html", "response could not be decompressed")
    return bytes(body)


def _fetch_one_hop(client, target, deadline, now):
    """Request one validated URL (trying up to MAX_ADDRESSES_TRIED of its checked addresses). Returns
    (status, headers, body_or_None). The body is only read for a 2xx answer."""
    last_error = None
    for address in target.addresses[:MAX_ADDRESSES_TRIED]:
        if now() > deadline:
            raise ImportFailure("timeout", "total time limit reached")
        headers = {
            "Host": _host_header(target),
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        # For https the certificate is checked against the NAME, although we connect to the checked address.
        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        try:
            with client.stream("GET", _connect_url(target, address), headers=headers, extensions=extensions) as response:
                status = response.status_code
                if not 200 <= status < 300:
                    return status, response.headers, None
                main_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if main_type not in ACCEPTED_CONTENT_TYPES:
                    raise ImportFailure("not_html", f"content type {main_type or 'missing'!r}")
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_HTML_BYTES:
                    raise ImportFailure("too_large", "Content-Length above the limit")
                return status, response.headers, _read_limited_body(response, deadline, now)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            raise ImportFailure("timeout", "request timed out")
        except httpx.ConnectError as error:
            last_error = error                  # try the next checked address
        except httpx.HTTPError as error:
            raise ImportFailure("unreachable", f"HTTP error: {type(error).__name__}")
    raise ImportFailure("unreachable", f"could not connect: {last_error}")


def fetch_public_page(url, resolver=None, transport=None, now=time.monotonic):
    """Download one public HTML page, following at most MAX_REDIRECTS redirects. Every URL, the first one and every
    redirect target, goes through validate_public_url() before anything is requested."""
    deadline = now() + TOTAL_TIMEOUT
    current = url
    redirects = 0
    with _make_client(transport) as client:
        while True:
            target = validate_public_url(current, resolver)
            status, headers, body = _fetch_one_hop(client, target, deadline, now)

            if status in (301, 302, 303, 307, 308):
                location = headers.get("location", "")
                if not location or len(location) > MAX_URL_CHARS:
                    raise ImportFailure("unreachable", "redirect without a usable Location")
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    raise ImportFailure("too_many_redirects", f"more than {MAX_REDIRECTS} redirects")
                current = urljoin(target.url, location)       # then it is validated again at the top of the loop
                continue

            if status in (401, 403, 407, 429, 451) or status == 999:
                raise ImportFailure("blocked_by_site", f"HTTP {status}")
            if status in (404, 410):
                raise ImportFailure("not_found", f"HTTP {status}")
            if body is None:
                raise ImportFailure("unreachable", f"HTTP {status}")

            charset_match = re.search(r"charset=([\w\-]+)", headers.get("content-type", ""), re.I)
            return FetchedPage(requested_url=url.strip(), final_url=target.url, redirect_count=redirects,
                               body=body, charset=charset_match.group(1) if charset_match else None)


# ---------------------------------------------------------------------------------------------------------------
# Part 3: turning HTML into job text
# ---------------------------------------------------------------------------------------------------------------
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "ul", "ol", "table", "tr", "blockquote", "pre", "dl", "dt",
               "dd", "figure", "figcaption", "details", "summary", "address", "body", "form", "fieldset", "caption",
               "hr", "header", "footer"}
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "canvas", "nav", "aside", "head", "input",
              "select", "textarea", "button", "object", "embed", "audio", "video", "picture", "map", "dialog"}
_DROP_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog", "alertdialog"}
_COOKIE_BANNER = re.compile(r"cookie|consent|onetrust|gdpr|cc-window", re.I)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)

# Titles of CAPTCHA / bot-check / login pages
_CHALLENGE_TITLES = re.compile(
    r"just a moment|attention required|access denied|are you a robot|are you human|verify you are (?:a )?human|"
    r"security check|captcha|checking your browser|request blocked|unusual traffic|^\s*(?:sign in|log in|login)\b", re.I)
# Words that a short, visible challenge page shows
_CHALLENGE_TEXT = re.compile(
    r"captcha|are you a robot|verify you are (?:a )?human|enable javascript|javascript is (?:disabled|required)|"
    r"please enable cookies|access denied", re.I)
# Markers in the HTML itself that bot-protection services use on their challenge pages (a reCAPTCHA script on a
# normal application form is NOT in this list)
_CHALLENGE_HTML = re.compile(r"cf-chl|challenge-platform|px-captcha|captcha-delivery|id=\"challenge-form\"", re.I)


def _attr_text(tag, name):
    value = tag.attrs.get(name) if tag.attrs else None
    if isinstance(value, list):
        return " ".join(value)
    return value or ""


def _is_dropped(tag):
    """True for elements that are not job content: scripts, navigation, page chrome, cookie banners, hidden text."""
    name = tag.name
    if name in _DROP_TAGS:
        return True
    if name in ("header", "footer") and tag.find_parent(["article", "main"]) is None:
        return True                           # page-level header/footer; one inside an article is part of the job
    attrs = tag.attrs or {}
    if "hidden" in attrs or attrs.get("aria-hidden") == "true" or _HIDDEN_STYLE.search(_attr_text(tag, "style")):
        return True
    if _attr_text(tag, "role").strip().lower() in _DROP_ROLES:
        return True
    return bool(_COOKIE_BANNER.search(_attr_text(tag, "id") + " " + _attr_text(tag, "class")))


def element_to_text(root, skip_dropped=True):
    """Visible text of an element with line breaks where the page has them (headings and list items on their own
    lines). Iterative, so deeply nested HTML cannot crash the server."""
    pieces = []
    stack = [(root, False)]
    while stack:
        node, closing = stack.pop()
        if closing:
            if node.name != "li":                 # a list item ends where the next "- " begins
                pieces.append("\n\n" if node.name in _HEADING_TAGS else "\n")
            continue
        if isinstance(node, Comment):
            continue
        if isinstance(node, NavigableString):
            pieces.append(re.sub(r"\s+", " ", str(node)))
            continue
        if not isinstance(node, Tag):
            continue
        if skip_dropped and node is not root and _is_dropped(node):
            continue
        name = node.name
        if name == "br":
            pieces.append("\n")
            continue
        if name == "li":
            pieces.append("\n- ")
            stack.append((node, True))
        elif name in _HEADING_TAGS:
            pieces.append("\n\n")
            stack.append((node, True))
        elif name in _BLOCK_TAGS:
            pieces.append("\n")
            stack.append((node, True))
        stack.extend((child, False) for child in reversed(node.contents))
    return _tidy_text("".join(pieces))


def _tidy_text(text):
    lines, blank = [], True
    for line in (re.sub(r"[ \t\u00a0]+", " ", raw).strip() for raw in text.replace("\r", "").split("\n")):
        if line in ("-", "•"):
            continue
        if not line:
            if not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _html_fragment_to_text(fragment):
    """A JSON-LD description (HTML, sometimes escaped twice, sometimes plain text) as readable text."""
    if not isinstance(fragment, str):
        return ""
    if "<" not in fragment and "&lt;" in fragment:
        fragment = html.unescape(fragment)
    fragment = re.sub(r"(?:\\r)?\\n", "\n", fragment)   # some platforms leave a literal backslash-n in the data
    soup = BeautifulSoup(fragment, "html.parser")
    return element_to_text(soup, skip_dropped=False)


# ---- schema.org JobPosting (JSON-LD) ----
def _is_job_posting(node):
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and re.split(r"[/:#]", t)[-1].lower() == "jobposting" for t in types)


def _iter_job_postings(data):
    stack = [data]
    visited = 0
    while stack and visited < 5000:
        node = stack.pop()
        visited += 1
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            if _is_job_posting(node):
                yield node
            stack.extend(reversed([v for v in node.values() if isinstance(v, (dict, list))]))


def _plain(value):
    return " ".join(html.unescape(value).split()) if isinstance(value, str) else ""


def _name_of(value):
    if isinstance(value, list):
        value = next((v for v in value if _name_of(v)), None)
    if isinstance(value, dict):
        return _plain(value.get("name") or value.get("legalName") or "")
    return _plain(value)


def _location_of(posting):
    places = posting.get("jobLocation")
    places = places if isinstance(places, list) else [places]
    found = []
    for place in places:
        if not isinstance(place, dict):
            continue
        address = place.get("address")
        if isinstance(address, dict):
            country = address.get("addressCountry")
            country = country.get("name") if isinstance(country, dict) else country
            text = ", ".join(p for p in (_plain(address.get("addressLocality")), _plain(address.get("addressRegion")),
                                         _plain(country)) if p)
        else:
            text = _plain(address) or _plain(place.get("name"))
        if text and text not in found:
            found.append(text)
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        found.append("Remote")
    return "; ".join(found[:3])


def _salary_of(posting):
    salary = posting.get("baseSalary")
    if not isinstance(salary, dict):
        return ""
    value = salary.get("value")
    currency = _plain(salary.get("currency"))
    unit = ""
    if isinstance(value, dict):
        unit = _plain(value.get("unitText"))
        low, high, single = value.get("minValue"), value.get("maxValue"), value.get("value")
    else:
        low = high = None
        single = value

    def number(item):
        if isinstance(item, bool) or item in (None, ""):
            return ""
        if isinstance(item, (int, float)):
            return f"{item:,.0f}" if float(item).is_integer() else f"{item:,.2f}"
        return _plain(str(item))

    amount = f"{number(low)}-{number(high)}" if number(low) and number(high) else number(single or low or high)
    if not amount:
        return ""
    return " ".join(p for p in (currency, amount, f"per {unit.lower()}" if unit else "") if p)


def _date_of(value):
    text = _plain(value)
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else text[:40]


def job_posting_text(posting):
    """Readable text built from a JobPosting. Only values the page really contains are used; missing ones are
    skipped. The lines are laid out so the existing Smart Intake Parser sorts them into the five fields."""
    title = _plain(posting.get("title") or posting.get("name"))
    description = _html_fragment_to_text(posting.get("description"))
    company = _name_of(posting.get("hiringOrganization"))
    employment = posting.get("employmentType")
    employment = ", ".join(_plain(e).replace("_", " ").capitalize() for e in
                           (employment if isinstance(employment, list) else [employment]) if _plain(e))
    metadata = [
        f"Company: {company}" if company else "",
        f"Salary: {_salary_of(posting)}" if _salary_of(posting) else "",
        f"Location: {_location_of(posting)}" if _location_of(posting) else "",
        f"Employment type: {employment}" if employment else "",
        f"Date posted: {_date_of(posting.get('datePosted'))}" if _date_of(posting.get("datePosted")) else "",
        f"Apply by: {_date_of(posting.get('validThrough'))}" if _date_of(posting.get("validThrough")) else "",
    ]
    lines = [title, ""] + [line for line in metadata if line] + ["", "Job Description", description]
    return _tidy_text("\n".join(lines)), title, company, description


def find_job_posting(soup):
    """The first schema.org JobPosting found in a <script type="application/ld+json"> block, or None."""
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (script.string or script.get_text() or "").strip()
        raw = re.sub(r"^\s*(?:<!--|//\s*<!\[CDATA\[|/\*\s*<!\[CDATA\[\s*\*/)", "", raw)
        raw = re.sub(r"(?:-->|//\s*\]\]>|/\*\s*\]\]>\s*\*/)\s*$", "", raw).strip()
        try:
            data = json.loads(raw, strict=False)
        except (ValueError, RecursionError):
            continue
        for posting in _iter_job_postings(data):
            return posting
    return None


def _looks_like_block_page(title, text, html_lowered):
    """A CAPTCHA, bot-check or login wall instead of a job. We stop there and never try to pass it."""
    if _CHALLENGE_TITLES.search(title or ""):
        return True
    return len(text) < 1500 and bool(_CHALLENGE_TEXT.search(text) or _CHALLENGE_HTML.search(html_lowered))


@dataclass
class ExtractedPage:
    raw_posting: str
    page_title: str
    company_name: str
    structured_job_data_found: bool
    used_structured_text: bool


def extract_job_page(body, charset=None):
    """Job text from page bytes: schema.org JobPosting data when the page has usable data, otherwise the visible
    text of the page. Raises ImportFailure("no_content") for pages that hold no readable job."""
    try:
        soup = BeautifulSoup(body, "html.parser", from_encoding=charset)
    except Exception as error:                      # unreadable markup must never crash the server
        raise ImportFailure("no_content", f"HTML could not be parsed: {type(error).__name__}")

    page_title = _plain(soup.title.get_text()) if soup.title else ""
    page_title = page_title[:200]
    posting = find_job_posting(soup)

    if posting is not None:
        text, title, company, description = job_posting_text(posting)
        # Usable = a title and a real description. Otherwise the visible page text is used instead.
        if title and len(description) >= MIN_STRUCTURED_DESCRIPTION_CHARS:
            return ExtractedPage(text[:MAX_POSTING_CHARS].strip(), page_title, company, True, True)
    company = _name_of(posting.get("hiringOrganization")) if posting else ""

    # Fallback: the visible text. Prefer <main>, but only when it holds most of the page's text.
    root = soup.body or soup
    page_text = element_to_text(root)
    main = root.find("main") or root.find(attrs={"role": "main"})
    if main is not None:
        main_text = element_to_text(main)
        if len(main_text) >= MIN_POSTING_CHARS and len(main_text) >= 0.5 * len(page_text):
            page_text = main_text

    first_heading = root.find("h1")
    heading = _plain(first_heading.get_text()) if first_heading else ""
    if _looks_like_block_page(heading or page_title, page_text, body[:200_000].decode("utf-8", "ignore").lower()):
        raise ImportFailure("blocked_by_site", "challenge or login page")
    if len(page_text) < MIN_POSTING_CHARS:
        raise ImportFailure("no_content", "too little readable text (JavaScript-only page?)")
    return ExtractedPage(page_text[:MAX_POSTING_CHARS].strip(), page_title, company, posting is not None, False)


# ---------------------------------------------------------------------------------------------------------------
# Part 4: the one function the API calls
# ---------------------------------------------------------------------------------------------------------------
# Used ONLY by backend/demo_import_server.py and the tests to replace the real network with canned pages.
_network_for_demo = {"resolver": None, "transport": None}


def use_fake_network_for_demo(resolver=None, transport=None):
    _network_for_demo["resolver"], _network_for_demo["transport"] = resolver, transport


def _display_domain(host):
    return host[4:] if host.startswith("www.") else host


def import_job_url(url, resolver=None, transport=None):
    """Import one public job page. Returns a dict; raises ImportFailure when the page cannot be imported.

        requested_url, final_url, source_domain, redirect_count, https, structured_job_data_found, page_title,
        company_name, raw_posting, extracted_fields (the five Smart Intake fields), timings_ms
    """
    resolver = resolver or _network_for_demo["resolver"]
    transport = transport or _network_for_demo["transport"]

    started = time.perf_counter()
    page = fetch_public_page(url, resolver=resolver, transport=transport)
    fetched = time.perf_counter()
    extracted = extract_job_page(page.body, page.charset)
    parsed = time.perf_counter()
    fields = parse_posting(extracted.raw_posting).to_dict()     # the existing Smart Intake Parser, not a second one
    done = time.perf_counter()

    final = urlsplit(page.final_url)
    return {
        "requested_url": page.requested_url,
        "final_url": page.final_url,
        "source_domain": _display_domain((final.hostname or "").lower()),
        "redirect_count": page.redirect_count,
        "https": final.scheme == "https",
        "structured_job_data_found": extracted.structured_job_data_found,
        "page_title": extracted.page_title or None,
        "company_name": extracted.company_name or None,
        "raw_posting": extracted.raw_posting,
        "extracted_fields": fields,
        "timings_ms": {"fetch": round((fetched - started) * 1000, 1), "html_extract": round((parsed - fetched) * 1000, 1),
                       "intake_parse": round((done - parsed) * 1000, 1)},
    }
