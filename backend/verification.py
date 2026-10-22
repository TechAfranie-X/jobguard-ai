"""Verification checks (Milestone 14): where is the job hosted, and are the contact details consistent?

This is the THIRD, independent layer next to the DistilBERT risk score and the warning-sign scanner:

    1. machine-learning risk     (DistilBERT)
    2. transparent text signals  (backend/scam_signals.py)
    3. verification checks       (this file): URL, hosting and contact-domain facts

Rules of this file (they are tested in backend/test_verification.py):
  * It reports FACTS, never verdicts. There is no score, no percentage and no "safe / unsafe / legitimate / fraud".
    A domain match does not prove a job is genuine (websites are copied and hacked), and a mismatch does not prove
    a problem (companies use other domains and recruiting platforms).
  * It is deterministic and does no network access at all. It never opens the company website. It only compares
    names that were already given to it.
  * It never changes the text or the score of the other layers, and the other layers never read its output.

Check statuses: "confirmed" (the details are consistent), "attention" (worth a closer look), "info" (a neutral
fact) and "not_checked" (not enough information was given).
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import tldextract

# Public-suffix aware domain splitting. The data comes from the snapshot bundled inside the tldextract package:
# suffix_list_urls=() forbids any download, cache_dir=None writes nothing to disk. "Private" suffixes are included,
# so one customer's page on a shared host (name.github.io) is not treated as the same site as another customer's.
_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)

STATUSES = ("confirmed", "attention", "info", "not_checked")
# Display order: things worth a closer look come first
_STATUS_ORDER = {"attention": 0, "confirmed": 1, "info": 2, "not_checked": 3}


# ---------------------------------------------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------------------------------------------
def normalize_host(value):
    """Lowercase ASCII host name (international names become xn-- names), or None if it is not a usable host."""
    if not isinstance(value, str):
        return None
    host = value.strip().lower().rstrip(".")
    if not host or " " in host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if len(host) > 253 or not re.fullmatch(r"[a-z0-9_.\-]+", host) or ".." in host or host.startswith((".", "-")):
        return None
    return host


def host_from_website(value):
    """The host of a web address the user typed ("https://www.company.com/about" or just "company.com")."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    try:
        parts = urlsplit(text)
        host = normalize_host(parts.hostname or "")
    except ValueError:
        return None
    if not host or "." not in host or re.fullmatch(r"[0-9.]+", host):      # no IP addresses, no one-word names
        return None
    return host


def registered_domain(host):
    """The part of a host that someone registered: jobs.company.com -> company.com, a.b.company.co.uk ->
    company.co.uk, company.com.evil.test -> evil.test. Unknown endings fall back to the last two labels."""
    registered = _EXTRACTOR(host).top_domain_under_public_suffix
    if registered:
        return registered
    labels = host.split(".")
    return ".".join(labels[-2:])


def _label_and_suffix(registered):
    extracted = _EXTRACTOR(registered)
    if extracted.domain and extracted.suffix:
        return extracted.domain, extracted.suffix
    labels = registered.split(".")
    return (labels[-2], labels[-1]) if len(labels) >= 2 else (registered, "")


def parse_email(value):
    """(local part, normalized domain) of an email address, or None if it does not look like one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    match = re.fullmatch(r"([^@\s]{1,64})@([^@\s]+)", text)
    if not match:
        return None
    domain = host_from_website(match.group(2))
    return (match.group(1), domain) if domain else None


def has_punycode(host):
    return any(label.startswith("xn--") for label in host.split("."))


def _readable_host(host):
    """Show an xn-- host in its Unicode form too, when that is possible."""
    try:
        text = host.encode("ascii").decode("idna")
    except UnicodeError:
        return host
    return host if text == host else f"{host} ({text})"


# ---------------------------------------------------------------------------------------------------------------
# Transparent lists
# ---------------------------------------------------------------------------------------------------------------
# Free / personal email providers. Matched against the exact email domain.
PERSONAL_EMAIL_PROVIDERS = {
    "gmail.com": "Gmail", "googlemail.com": "Gmail",
    "yahoo.com": "Yahoo", "yahoo.co.uk": "Yahoo", "yahoo.co.in": "Yahoo", "yahoo.ca": "Yahoo", "yahoo.fr": "Yahoo",
    "yahoo.de": "Yahoo", "yahoo.es": "Yahoo", "yahoo.it": "Yahoo", "yahoo.com.au": "Yahoo", "yahoo.com.br": "Yahoo",
    "ymail.com": "Yahoo", "rocketmail.com": "Yahoo",
    "hotmail.com": "Hotmail", "hotmail.co.uk": "Hotmail", "hotmail.fr": "Hotmail", "hotmail.de": "Hotmail",
    "hotmail.it": "Hotmail", "hotmail.es": "Hotmail",
    "outlook.com": "Outlook", "outlook.fr": "Outlook", "outlook.de": "Outlook", "outlook.es": "Outlook",
    "outlook.it": "Outlook",
    "live.com": "Microsoft Live", "live.co.uk": "Microsoft Live", "live.fr": "Microsoft Live", "msn.com": "MSN",
    "icloud.com": "iCloud", "me.com": "iCloud", "mac.com": "iCloud",
    "protonmail.com": "Proton Mail", "proton.me": "Proton Mail", "pm.me": "Proton Mail",
    "aol.com": "AOL", "gmx.com": "GMX", "gmx.net": "GMX", "mail.com": "Mail.com", "yandex.com": "Yandex",
    "yandex.ru": "Yandex", "qq.com": "QQ Mail", "163.com": "NetEase Mail", "126.com": "NetEase Mail",
}


@dataclass(frozen=True)
class AtsPlatform:
    """A recruiting platform that hosts job pages for many companies."""

    name: str
    exact_hosts: tuple = ()         # the host must be exactly one of these
    host_suffixes: tuple = ()       # or end with one of these (the platform gives each customer a subdomain)


# Host names checked in October 2026: Greenhouse, Lever, Ashby and SmartRecruiters against the vendors' own
# documentation; Workday and iCIMS from third-party articles and vendor community pages (sources: docs/job_verification.md);
# Workable and BambooHR are well-known public patterns that were not separately sourced. Being on this list only
# means "this is a known platform". Anyone can open an account on these platforms, so it is NOT a sign of authenticity.
ATS_PLATFORMS = (
    AtsPlatform("Greenhouse", exact_hosts=("boards.greenhouse.io", "job-boards.greenhouse.io")),
    AtsPlatform("Lever", exact_hosts=("jobs.lever.co", "jobs.eu.lever.co")),
    AtsPlatform("Ashby", exact_hosts=("jobs.ashbyhq.com",)),
    AtsPlatform("Workday", host_suffixes=(".myworkdayjobs.com", ".myworkdaysite.com")),
    AtsPlatform("iCIMS", host_suffixes=(".icims.com",)),
    AtsPlatform("SmartRecruiters", exact_hosts=("jobs.smartrecruiters.com", "careers.smartrecruiters.com")),
    AtsPlatform("Workable", exact_hosts=("apply.workable.com",)),
    AtsPlatform("BambooHR", host_suffixes=(".bamboohr.com",)),
)


def detect_ats(host):
    """The AtsPlatform a host belongs to, or None. Exact hosts and dot-prefixed suffixes only, so
    jobs.lever.co.evil.test or notmyworkdayjobs.com do not match."""
    for platform in ATS_PLATFORMS:
        if host in platform.exact_hosts or any(host.endswith(suffix) for suffix in platform.host_suffixes):
            return platform
    return None


# Domains that are often imitated. Only characters that are easy to confuse are compared (micros0ft, paypaI).
WELL_KNOWN_DOMAINS = ("microsoft.com", "paypal.com", "google.com", "amazon.com", "apple.com", "linkedin.com",
                      "indeed.com", "facebook.com", "netflix.com", "dropbox.com", "adobe.com", "walmart.com")

# Words often added to a real name to build a similar-looking domain (acme -> acme-careers, acmejobs)
_ADDED_WORDS = ("careers", "career", "jobs", "job", "hr", "hiring", "recruit", "recruiting", "recruitment", "talent",
                "staffing", "apply", "official", "team", "work")


# ---------------------------------------------------------------------------------------------------------------
# Lookalike detection (conservative on purpose)
# ---------------------------------------------------------------------------------------------------------------
def _skeleton(label):
    """A label with easily confused characters folded together: 0->o, 1/i->l, 3->e, 5->s, rn->m, vv->w."""
    text = label.lower().replace("rn", "m").replace("vv", "w")
    return text.translate(str.maketrans({"0": "o", "1": "l", "i": "l", "3": "e", "5": "s"}))


def _edit_distance(a, b):
    """Optimal string alignment distance: insert, delete, replace or swap two neighbouring letters."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[-1][-1]


def lookalike_reason(domain_a, domain_b):
    """Why two DIFFERENT registered domains look alike, or None. Short names are never compared by edit distance, and
    a different ending alone (company.com / company.net) is not flagged."""
    if domain_a == domain_b:
        return None
    label_a, _ = _label_and_suffix(domain_a)
    label_b, _ = _label_and_suffix(domain_b)
    if label_a == label_b or has_punycode(domain_a) or has_punycode(domain_b):
        return None
    if len(label_a) >= 4 and len(label_b) >= 4 and _skeleton(label_a) == _skeleton(label_b):
        return "they differ only by characters that are easy to confuse (such as 0 and o, or rn and m)"
    if min(len(label_a), len(label_b)) >= 7 and _edit_distance(label_a, label_b) == 1:
        return "they differ by a single character"
    short, long_ = sorted((label_a, label_b), key=len)
    if len(short) >= 4:
        short_words, long_words = set(short.split("-")), set(long_.split("-"))
        if short_words < long_words:
            return "one is the other with extra words added"
        for word in _ADDED_WORDS:
            if long_ in (short + word, word + short, short + "-" + word, word + "-" + short):
                return "one is the other with a recruiting word added"
    return None


def _well_known_lookalike(domain):
    label, _ = _label_and_suffix(domain)
    if has_punycode(domain):
        return None
    for known in WELL_KNOWN_DOMAINS:
        known_label, _ = _label_and_suffix(known)
        if domain != known and label != known_label and len(label) >= 4 and _skeleton(label) == _skeleton(known_label):
            return known
    return None


# ---------------------------------------------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------------------------------------------
def _check(check_id, status, title, detail, result=None):
    assert status in STATUSES
    return {"id": check_id, "status": status, "title": title, "detail": detail, "result": result}


def _job_host_check(job_host, company_host):
    job_domain = registered_domain(job_host)
    platform = detect_ats(job_host)
    if company_host:
        company_domain = registered_domain(company_host)
        if job_domain == company_domain:
            return _check(
                "job_host", "confirmed", f"Job page is on the company website's domain ({company_domain})",
                f"The page is hosted on {job_host}, which belongs to the same registered domain as the company website "
                f"you entered. This only checks consistency. Websites can be copied or compromised, so a match does "
                f"not prove the posting is genuine.", "MATCH")
        if platform:
            return _check(
                "job_host", "info", f"Hosted on {platform.name}",
                f"Hosted on a recognized recruiting platform ({job_host}), not on the company website you entered "
                f"({company_domain}). Many companies post jobs through third-party platforms, and anyone can open an "
                f"account on them, so this does not prove the posting is genuine.", "KNOWN_ATS")
        return _check(
            "job_host", "attention", "Job is hosted on a different domain than the company website",
            f"The job page is on {job_domain}, while the company website you entered is {company_domain}. Companies "
            f"often use other domains or third-party platforms, so this alone does not mean anything is wrong. Check "
            f"that the company's own careers page lists this job.", "DIFFERENT_DOMAIN")
    if platform:
        return _check(
            "job_host", "info", f"Hosted on {platform.name}",
            f"Hosted on a recognized recruiting platform ({job_host}). Many companies post jobs through third-party "
            f"platforms, and anyone can open an account on them, so this does not prove the posting is genuine.",
            "KNOWN_ATS")
    return _check(
        "job_host", "not_checked", "Job host not compared",
        f"The job page is hosted on {job_host}. Add the company website to compare where the job is hosted.",
        "NOT_CHECKED")


def _recruiter_check(email, company_host):
    parsed = parse_email(email)
    if parsed is None:
        return _check("recruiter_email", "not_checked", "Recruiter email could not be read",
                      "That does not look like an email address, so it was not checked.", "NOT_CHECKED")
    _, email_host = parsed
    provider = PERSONAL_EMAIL_PROVIDERS.get(email_host)
    if provider:
        return _check(
            "recruiter_email", "attention", f"Recruiter email uses {provider}",
            "This recruiter email uses a personal email provider. Recruiters representing established companies "
            "generally use a company domain. Verify the sender independently.", "PERSONAL_EMAIL")
    email_domain = registered_domain(email_host)
    if company_host:
        company_domain = registered_domain(company_host)
        if email_domain == company_domain:
            return _check(
                "recruiter_email", "confirmed", "Recruiter email domain matches the company website",
                f"The email uses {email_host}, the same registered domain as the company website you entered "
                f"({company_domain}). Anyone can write an email that appears to come from a domain, so a match does "
                f"not prove the recruiter is genuine.", "MATCH")
        return _check(
            "recruiter_email", "attention", "Recruiter email domain differs from the company website",
            f"The email uses {email_domain}, while the company website you entered is {company_domain}. Recruiters "
            f"sometimes use a parent company or an agency, so this alone does not mean anything is wrong. Verify the "
            f"sender independently.", "MISMATCH")
    return _check(
        "recruiter_email", "not_checked", "Recruiter email domain not compared",
        f"The email uses {email_host}. Add the company website to compare it with the company's domain.",
        "NOT_CHECKED")


def _lookalike_check(job_host, company_host, email_host):
    """Collect every pair of domains that look alike. One check, no accusation."""
    findings = []
    company_domain = registered_domain(company_host) if company_host else None
    job_domain = registered_domain(job_host) if job_host else None
    email_domain = registered_domain(email_host) if email_host and email_host not in PERSONAL_EMAIL_PROVIDERS else None

    if company_domain and email_domain:
        reason = lookalike_reason(email_domain, company_domain)
        if reason:
            findings.append(f"The recruiter email domain ({email_domain}) and the company website ({company_domain}) "
                            f"look similar: {reason}.")
    if company_domain and job_domain and not detect_ats(job_host):
        reason = lookalike_reason(job_domain, company_domain)
        if reason:
            findings.append(f"The job page domain ({job_domain}) and the company website ({company_domain}) look "
                            f"similar: {reason}.")
    for name, domain in (("job page", job_domain if job_host and not detect_ats(job_host) else None),
                         ("recruiter email", email_domain)):
        known = _well_known_lookalike(domain) if domain else None
        if known:
            findings.append(f"The {name} domain ({domain}) resembles {known}, but is spelled with easily confused "
                            f"characters.")
    if not findings:
        return None
    return _check("lookalike_domain", "attention", "Possible lookalike domain",
                  " ".join(findings) + " Verify the domain manually. Similar names are sometimes innocent, for example "
                  "two unrelated companies.", "POSSIBLE_LOOKALIKE")


def _punycode_check(hosts):
    found = [host for host in hosts if host and has_punycode(host)]
    if not found:
        return None
    return _check(
        "punycode_domain", "attention", "Domain uses international (xn--) characters",
        f"{', '.join(_readable_host(h) for h in dict.fromkeys(found))} is written with international characters, "
        f"which can make one address look like another. Many sites legitimately use them. Verify the domain manually.",
        "PUNYCODE")


def _redirect_check(requested_url, final_host, redirect_count):
    requested_host = normalize_host(urlsplit(requested_url).hostname or "")
    if not redirect_count or not requested_host or not final_host:
        return None
    original, final = registered_domain(requested_host), registered_domain(final_host)
    if original == final:
        return None
    hops = f"{redirect_count} redirect" + ("" if redirect_count == 1 else "s")
    return _check(
        "redirect", "info", "This link redirected to a different domain",
        f"The link you entered was on {original}; the page loaded from {final} after {hops}. Redirects are common "
        f"(tracking links, link shorteners, recruiting platforms), but check that the final domain is the one you "
        f"expected.", "REDIRECTED")


def run_verification(final_url=None, requested_url=None, redirect_count=0, structured_job_data_found=False,
                     company_website=None, recruiter_email=None):
    """All checks for one analysis. Returns {"checks": [...]}, most important first. Pure function: it uses only
    its arguments and makes no network request."""
    checks = []
    company_host = host_from_website(company_website) if company_website else None
    parsed_email = parse_email(recruiter_email) if recruiter_email else None
    email_host = parsed_email[1] if parsed_email else None

    final_host = None
    if final_url:
        parts = urlsplit(final_url)
        final_host = normalize_host(parts.hostname or "")
        if final_host:
            if company_website and not company_host:
                checks.append(_check("job_host", "not_checked", "Company website could not be read",
                                     "Enter a web address such as https://company.com to compare it with where the "
                                     "job is hosted.", "NOT_CHECKED"))
            else:
                checks.append(_job_host_check(final_host, company_host))
            redirect = _redirect_check(requested_url or final_url, final_host, redirect_count)
            if redirect:
                checks.append(redirect)
            if parts.scheme == "https":
                checks.append(_check("https", "info", "Page loaded over HTTPS",
                                     "The connection to the page is encrypted. HTTPS does not show that the site or "
                                     "the job is genuine. It only protects information while it travels.", "HTTPS"))
            else:
                checks.append(_check("https", "attention", "This page is not using HTTPS",
                                     "The page loaded over plain HTTP, so information sent to it could be read by "
                                     "others on the network. Avoid entering personal details on pages like this. "
                                     "A missing HTTPS connection does not on its own show a problem with the job.",
                                     "HTTP"))
            if structured_job_data_found:
                checks.append(_check("structured_data", "info", "Structured job data detected",
                                     "The page exposes standardized schema.org JobPosting information. Many recruiting "
                                     "platforms publish this metadata. It is a normal feature, not a sign of "
                                     "authenticity, because anyone can add it to a web page.", "JOB_POSTING_DATA"))

    if recruiter_email:
        checks.append(_recruiter_check(recruiter_email, company_host))

    lookalike = _lookalike_check(final_host, company_host, email_host)
    if lookalike:
        checks.append(lookalike)
    punycode = _punycode_check([final_host, company_host, email_host])
    if punycode:
        checks.append(punycode)

    checks.sort(key=lambda check: _STATUS_ORDER[check["status"]])        # stable: attention first
    return {"checks": checks}
