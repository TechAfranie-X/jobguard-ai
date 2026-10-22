"""Tests for the verification checks (backend/verification.py).

Run from the project root:   python -m backend.test_verification

No model, no network and no test.csv. While the checks run, network access is switched off (any attempt to open a
socket fails the test), which proves that domain splitting uses only the data bundled with the library and that
nothing, not even the company website, is ever contacted.
"""

import ast
import re
import socket
import sys
from pathlib import Path

from backend import verification
from backend.verification import (ATS_PLATFORMS, PERSONAL_EMAIL_PROVIDERS, STATUSES, detect_ats, has_punycode,
                                  host_from_website, lookalike_reason, normalize_host, parse_email, registered_domain,
                                  run_verification)

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))


class NetworkAttempt(Exception):
    pass


def _no_network(*args, **kwargs):
    raise NetworkAttempt("a network connection was attempted")


def checks(**kwargs):
    return run_verification(**kwargs)["checks"]


def one(check_list, check_id):
    found = [c for c in check_list if c["id"] == check_id]
    return found[0] if found else None


def result_of(check_id, **kwargs):
    found = one(checks(**kwargs), check_id)
    return found["result"] if found else None


FORBIDDEN_WORDS = re.compile(r"\b(safe|unsafe|legit|legitimate|fraud|fraudulent|scam|scammer|trusted|trustworthy|verified|"
                             r"score|percent|rating)\b", re.I)


# ---------------------------------------------------------------------------------------------------------------
def test_domain_normalization():
    check("registered domain of jobs.company.com is company.com", registered_domain("jobs.company.com") == "company.com")
    check("www.company.com and company.com share one registered domain", registered_domain("www.company.com") == registered_domain("company.com"))
    check("a country-code suffix is understood: a.b.company.co.uk -> company.co.uk", registered_domain("a.b.company.co.uk") == "company.co.uk")
    check("company.com.evil.test belongs to evil.test, not to company.com", registered_domain("company.com.evil.test") == "evil.test")
    check("company.com.evil.example belongs to evil.example", registered_domain("company.com.evil.example") == "evil.example")
    check("two different .co.uk companies are different sites", registered_domain("a.co.uk") != registered_domain("b.co.uk"))
    check("shared hosts: x.github.io and y.github.io are different sites (private suffixes are respected)",
          registered_domain("x.github.io") == "x.github.io" and registered_domain("x.github.io") != registered_domain("y.github.io"))
    check("an unknown ending falls back to the last two labels", registered_domain("careers.acme.example") == "acme.example")
    check("a host name is lowercased and loses a trailing dot", normalize_host("Jobs.Company.COM.") == "jobs.company.com")
    check("an international name becomes its xn-- form", normalize_host("b\u00fccher.de") == "xn--bcher-kva.de")
    check("host_from_website reads a bare domain", host_from_website("company.com") == "company.com")
    check("host_from_website reads a full address with path, query and uppercase",
          host_from_website("HTTPS://www.Company.com/about-us?ref=1#top") == "www.company.com")
    check("host_from_website rejects text, IP addresses and one-word names",
          all(host_from_website(v) is None for v in ["hello there", "1.2.3.4", "localhost", "", "   ", None, 5, "http://"]))
    check("parse_email: case, mailto: and surrounding spaces are handled",
          parse_email(" Recruiter@Company.COM ") == ("Recruiter", "company.com") and parse_email("mailto:a@b.co.uk") == ("a", "b.co.uk"))
    check("parse_email rejects things that are not email addresses",
          all(parse_email(v) is None for v in ["nope", "a@", "@b.com", "a@b", "a b@c.com", "a@@b.com", "", None, 7, "a@1.2.3.4"]))
    check("has_punycode finds an xn-- label anywhere in the host", has_punycode("xn--80ak6aa92e.com") and has_punycode("shop.xn--p1ai")
          and not has_punycode("company.com"))


def test_company_website_check():
    base = dict(final_url="https://jobs.company.com/apply/1", requested_url="https://jobs.company.com/apply/1")
    check("company.com vs jobs.company.com -> MATCH (confirmed)", result_of("job_host", **base, company_website="https://company.com") == "MATCH"
          and one(checks(**base, company_website="company.com"), "job_host")["status"] == "confirmed")
    check("www.company.com vs company.com -> MATCH",
          result_of("job_host", final_url="https://www.company.com/x", company_website="company.com") == "MATCH")
    check("a company website with a path and capital letters still matches",
          result_of("job_host", **base, company_website="HTTPS://WWW.COMPANY.COM/About/Us") == "MATCH")
    check("company.co.uk vs careers.company.co.uk -> MATCH",
          result_of("job_host", final_url="https://careers.company.co.uk/x", company_website="https://company.co.uk") == "MATCH")
    spoof = result_of("job_host", final_url="https://company.com.evil.test/x", company_website="https://company.com")
    check("company.com vs company.com.evil.test -> DIFFERENT_DOMAIN (not fooled)", spoof == "DIFFERENT_DOMAIN")
    check("evil-company.com vs company.com -> DIFFERENT_DOMAIN",
          result_of("job_host", final_url="https://evil-company.com/x", company_website="company.com") == "DIFFERENT_DOMAIN")
    check("x.github.io vs y.github.io -> DIFFERENT_DOMAIN",
          result_of("job_host", final_url="https://x.github.io/job", company_website="https://y.github.io") == "DIFFERENT_DOMAIN")
    diff = one(checks(final_url="https://careers.other-firm.com/x", company_website="company.com"), "job_host")
    check("unrelated domains -> DIFFERENT_DOMAIN with attention, but no accusation",
          diff["result"] == "DIFFERENT_DOMAIN" and diff["status"] == "attention"
          and not FORBIDDEN_WORDS.search(diff["title"] + " " + diff["detail"])
          and "does not mean anything is wrong" in diff["detail"], diff["title"])
    check("no company website -> NOT_CHECKED (not_checked)",
          result_of("job_host", final_url="https://careers.other-firm.com/x") == "NOT_CHECKED"
          and one(checks(final_url="https://careers.other-firm.com/x"), "job_host")["status"] == "not_checked")
    unreadable = one(checks(final_url="https://careers.other-firm.com/x", company_website="not a website"), "job_host")
    check("an unreadable company website is reported as not checked, not as a mismatch",
          unreadable["status"] == "not_checked" and "could not be read" in unreadable["title"])
    check("a blank company website counts as not given", result_of("job_host", final_url="https://a.example-firm.com/x", company_website="  ") == "NOT_CHECKED")


def test_ats_detection():
    samples = {"Greenhouse": ["boards.greenhouse.io", "job-boards.greenhouse.io"], "Lever": ["jobs.lever.co", "jobs.eu.lever.co"],
               "Ashby": ["jobs.ashbyhq.com"], "Workday": ["acme.wd5.myworkdayjobs.com", "x.wd12.myworkdayjobs.com", "wd5.myworkdaysite.com"],
               "iCIMS": ["careers-acme.icims.com", "jobs-acme.icims.com"],
               "SmartRecruiters": ["jobs.smartrecruiters.com", "careers.smartrecruiters.com"], "Workable": ["apply.workable.com"],
               "BambooHR": ["acme.bamboohr.com"]}
    for name, hosts in samples.items():
        found = [detect_ats(h) for h in hosts]
        check(f"{name} hosts are recognized as a recruiting platform", all(f and f.name == name for f in found), str(hosts))
    check("the required six platforms are on the list",
          {"Greenhouse", "Lever", "Ashby", "Workday", "iCIMS", "SmartRecruiters"} <= {p.name for p in ATS_PLATFORMS})
    fakes = ["jobs.lever.co.evil.test", "lever.co", "notlever.co", "boards.greenhouse.io.evil.test", "evil-greenhouse.io", "greenhouse.io",
             "notmyworkdayjobs.com", "myworkdayjobs.com", "icims.com", "xicims.com", "jobs.ashbyhq.com.attacker.com", "company.com",
             # a real platform name in the MIDDLE of an attacker's host (the subdomain-suffix platforms)
             "acme.wd5.myworkdayjobs.com.evil.test", "wd5.myworkdaysite.com.evil.test", "careers-acme.icims.com.evil.test",
             "acme.bamboohr.com.evil.test"]
    check("look-alike hosts are NOT recognized as a platform", all(detect_ats(h) is None for h in fakes), str([h for h in fakes if detect_ats(h)]))
    for company in (None, "https://acme.com"):
        c = one(checks(final_url="https://boards.greenhouse.io/acme/jobs/1", company_website=company), "job_host")
        check(f"a platform-hosted job is KNOWN_ATS (info){' with a company website' if company else ''}",
              c["result"] == "KNOWN_ATS" and c["status"] == "info" and c["title"] == "Hosted on Greenhouse")
    c = one(checks(final_url="https://jobs.lever.co/acme/1"), "job_host")
    check("the platform text says 'Hosted on a recognized recruiting platform', never 'verified'",
          "Hosted on a recognized recruiting platform" in c["detail"] and "does not prove" in c["detail"]
          and not FORBIDDEN_WORDS.search(c["title"] + " " + c["detail"]))
    check("a company's own domain wins over the platform list",
          result_of("job_host", final_url="https://careers-acme.icims.com/jobs/1", company_website="https://careers-acme.icims.com") == "MATCH")


def test_recruiter_email_checks():
    personal = one(checks(recruiter_email="recruiter@gmail.com"), "recruiter_email")
    check("recruiter@gmail.com -> personal email, needs attention", personal["result"] == "PERSONAL_EMAIL" and personal["status"] == "attention")
    check("the title names the provider", personal["title"] == "Recruiter email uses Gmail")
    check("the message is the agreed sentence",
          personal["detail"] == "This recruiter email uses a personal email provider. Recruiters representing established companies "
                                "generally use a company domain. Verify the sender independently.")
    check("the personal-email message does not call it fraud", not FORBIDDEN_WORDS.search(personal["title"] + " " + personal["detail"]))
    for domain, name in [("yahoo.com", "Yahoo"), ("hotmail.com", "Hotmail"), ("outlook.com", "Outlook"), ("icloud.com", "iCloud"),
                         ("protonmail.com", "Proton Mail"), ("googlemail.com", "Gmail"), ("yahoo.co.uk", "Yahoo")]:
        got = one(checks(recruiter_email=f"x@{domain}", company_website="https://acme.com"), "recruiter_email")
        check(f"{domain} is a personal provider ({name}), even when a company website is given",
              got["result"] == "PERSONAL_EMAIL" and name in got["title"])
    for tricky in ["x@gmail.com.evil.test", "x@gmail.co", "x@mygmail.com", "x@gmail-careers.com", "x@yahoo.evil.com"]:
        got = one(checks(recruiter_email=tricky, company_website="https://acme.com"), "recruiter_email")
        check(f"{tricky.split('@')[1]} is NOT mistaken for a personal provider", got["result"] != "PERSONAL_EMAIL")
    check("all listed personal domains are lowercase and distinct", all(d == d.lower() for d in PERSONAL_EMAIL_PROVIDERS))

    check("recruiter@company.com vs company.com -> MATCH (confirmed)",
          result_of("recruiter_email", recruiter_email="recruiter@company.com", company_website="company.com") == "MATCH"
          and one(checks(recruiter_email="recruiter@company.com", company_website="company.com"), "recruiter_email")["status"] == "confirmed")
    check("an email on a subdomain (hr@mail.company.com) matches company.com",
          result_of("recruiter_email", recruiter_email="hr@mail.company.com", company_website="https://www.company.com") == "MATCH")
    check("an email in capitals still matches", result_of("recruiter_email", recruiter_email="HR@COMPANY.COM", company_website="company.com") == "MATCH")
    mismatch = one(checks(recruiter_email="hr@staffing-agency.com", company_website="company.com"), "recruiter_email")
    check("a different recruiter domain -> MISMATCH, as a fact and not an accusation",
          mismatch["result"] == "MISMATCH" and mismatch["status"] == "attention" and not FORBIDDEN_WORDS.search(mismatch["title"] + mismatch["detail"])
          and "does not mean anything is wrong" in mismatch["detail"])
    check("recruiter@company.com.evil.test vs company.com -> MISMATCH",
          result_of("recruiter_email", recruiter_email="x@company.com.evil.test", company_website="company.com") == "MISMATCH")
    check("a company-style email without a company website -> NOT_CHECKED",
          result_of("recruiter_email", recruiter_email="x@company.com") == "NOT_CHECKED")
    check("an unreadable email is reported as not checked", result_of("recruiter_email", recruiter_email="not an email") == "NOT_CHECKED")
    check("no recruiter email -> no email check at all", one(checks(final_url="https://a.example-firm.com/x"), "recruiter_email") is None)


def test_lookalike_domains():
    check("recruiter@cornpany.com vs company.com -> POSSIBLE_LOOKALIKE",
          result_of("lookalike_domain", recruiter_email="recruiter@cornpany.com", company_website="company.com") == "POSSIBLE_LOOKALIKE")
    c = one(checks(recruiter_email="recruiter@cornpany.com", company_website="company.com"), "lookalike_domain")
    check("the lookalike notice says 'Possible lookalike domain' and 'Verify the domain manually', and does not accuse",
          c["title"] == "Possible lookalike domain" and "Verify the domain manually" in c["detail"]
          and not re.search(r"imperson|phish|fake|fraud|scam", c["detail"], re.I) and c["status"] == "attention")
    positives = [("cornpany.com", "company.com"), ("company.com", "compnay.com"), ("companyy.com", "company.com"),
                 ("company-careers-example.com", "example.com"), ("acme-hr.com", "acme.com"), ("acmejobs.com", "acme.com"),
                 ("acme-careers.com", "acme.com"), ("c0mpany.com", "company.com"), ("vvidgets.com", "widgets.com"),
                 ("acmecorp1.com", "acmecorp2.com")]
    for a, b in positives:
        check(f"lookalike: {a} ~ {b}", lookalike_reason(a, b) is not None and lookalike_reason(b, a) is not None, str(lookalike_reason(a, b)))
    negatives = [("acme.com", "acme.net"), ("stripe.com", "strike.com"), ("meta.com", "metal.com"), ("apple.com", "maple.com"),
                 ("microsoft.com", "paypal.com"), ("ibm.com", "ibn.com"), ("company.com", "company.com"), ("acme.com", "orbit.com"),
                 ("northwind.com", "southwind.com"), ("bright.com", "brightpath.com")]
    for a, b in negatives:
        check(f"no lookalike: {a} / {b}", lookalike_reason(a, b) is None, str(lookalike_reason(a, b)))
    for fake in ["micros0ft.com", "paypaI.com", "paypa1.com", "linkedln.com", "amaz0n.com", "g00gle.com", "rnicrosoft.com"]:
        c = one(checks(final_url=f"https://{fake}/careers"), "lookalike_domain")
        check(f"well-known brand imitation {fake} is noticed", c is not None and "resembles" in c["detail"])
    for real in ["jobs.microsoft.com", "www.paypal.com", "careers.google.com", "boards.greenhouse.io", "company.com"]:
        check(f"the real domain {real} is not flagged", one(checks(final_url=f"https://{real}/x"), "lookalike_domain") is None)
    check("a platform host is not compared with the company name",
          one(checks(final_url="https://jobs.lever.co/acme/1", company_website="https://acme.com"), "lookalike_domain") is None)
    check("two unrelated domains give MISMATCH but no lookalike notice",
          result_of("recruiter_email", recruiter_email="x@orbit-hr.com", company_website="acme.com") == "MISMATCH"
          and one(checks(recruiter_email="x@orbit-hr.com", company_website="acme.com"), "lookalike_domain") is None)
    both = one(checks(final_url="https://acme-careers.com/x", company_website="acme.com", recruiter_email="x@acme-hr.com"), "lookalike_domain")
    check("job-page and recruiter findings are combined into ONE check", both is not None and both["detail"].count("look similar") == 2)


def test_punycode():
    c = one(checks(final_url="https://xn--pypal-4ve.com/x"), "punycode_domain")
    check("a job page on an xn-- domain -> attention notice", c is not None and c["status"] == "attention" and c["result"] == "PUNYCODE")
    check("an xn-- recruiter email domain is noticed", one(checks(recruiter_email="a@xn--80ak6aa92e.com"), "punycode_domain") is not None)
    check("an xn-- company website is noticed", one(checks(company_website="https://xn--80ak6aa92e.com", recruiter_email="a@acme.com"), "punycode_domain") is not None)
    check("a Unicode domain typed by the user is converted and noticed",
          one(checks(final_url="https://b\u00fccher.de/x"), "punycode_domain") is not None)
    check("the notice says to verify manually and does not accuse",
          "Verify the domain manually" in c["detail"] and not FORBIDDEN_WORDS.search(c["detail"] + c["title"]))
    check("ordinary domains produce no xn-- notice", one(checks(final_url="https://jobs.company.com/x", company_website="company.com"), "punycode_domain") is None)


def test_https_redirect_structured():
    https = one(checks(final_url="https://jobs.company.com/x"), "https")
    check("an HTTPS URL -> informational, not a 'confirmed' tick (HTTPS is not proof of anything)",
          https["result"] == "HTTPS" and https["status"] == "info" and https["title"] == "Page loaded over HTTPS")
    check("the HTTPS text says it is not proof of anything", "does not show that the site or the job is genuine" in https["detail"])
    http = one(checks(final_url="http://jobs.company.com/x"), "https")
    check("an HTTP URL -> notice 'This page is not using HTTPS'", http["result"] == "HTTP" and http["status"] == "attention"
          and http["title"] == "This page is not using HTTPS" and "does not on its own show a problem" in http["detail"])

    r = one(checks(final_url="https://careers.company.com/x", requested_url="https://bit.example-links.com/abc", redirect_count=2), "redirect")
    check("a redirect to a different domain -> info naming both domains and the count",
          r["status"] == "info" and r["title"] == "This link redirected to a different domain" and "example-links.com" in r["detail"]
          and "company.com" in r["detail"] and "2 redirects" in r["detail"] and not FORBIDDEN_WORDS.search(r["detail"]))
    check("a redirect inside the same registered domain is not reported",
          one(checks(final_url="https://www.company.com/x", requested_url="http://company.com/x", redirect_count=1), "redirect") is None)
    check("no redirect -> no redirect check", one(checks(final_url="https://company.com/x", requested_url="https://company.com/x", redirect_count=0), "redirect") is None)
    check("one redirect says '1 redirect'", "1 redirect." in one(checks(final_url="https://b.example-two.com/x", requested_url="https://a.example-one.com/x", redirect_count=1), "redirect")["detail"])

    s = one(checks(final_url="https://x.example-firm.com/", structured_job_data_found=True), "structured_data")
    check("structured JobPosting data -> 'Structured job data detected' (info)", s["status"] == "info" and s["title"] == "Structured job data detected")
    check("the structured-data text does not say the job is verified",
          "not a sign of authenticity" in s["detail"] and not FORBIDDEN_WORDS.search(s["detail"] + s["title"]))
    check("no structured data -> no check (absence is not reported as a problem)", one(checks(final_url="https://x.example-firm.com/"), "structured_data") is None)


def test_result_model():
    sample_inputs = [
        dict(final_url="https://jobs.company.com/x", requested_url="https://short.example-links.com/a", redirect_count=1,
             structured_job_data_found=True, company_website="company.com", recruiter_email="hr@company.com"),
        dict(final_url="http://company.com.evil.test/x", company_website="company.com", recruiter_email="hr@gmail.com"),
        dict(final_url="https://boards.greenhouse.io/a/jobs/1", company_website="a.com", recruiter_email="x@cornpany.com"),
        dict(final_url="https://xn--pypal-4ve.com/", recruiter_email="x@paypaI.com"),
        dict(),
    ]
    all_checks = [c for kwargs in sample_inputs for c in checks(**kwargs)]
    check("every check has id, status, title, detail and result", all(set(c) == {"id", "status", "title", "detail", "result"} for c in all_checks))
    check("statuses are only confirmed / attention / info / not_checked",
          {c["status"] for c in all_checks} <= {"confirmed", "attention", "info", "not_checked"} and STATUSES == ("confirmed", "attention", "info", "not_checked"))
    check("no title or detail contains a verdict word (safe, unsafe, legit, fraud, scam, verified, trusted, score)",
          not any(FORBIDDEN_WORDS.search(c["title"] + " " + c["detail"]) for c in all_checks),
          str([c["title"] for c in all_checks if FORBIDDEN_WORDS.search(c["title"] + " " + c["detail"])]))
    out = run_verification(**sample_inputs[0])
    check("the response is only a list of checks: no score, percentage or verdict field", set(out) == {"checks"})
    order = ["attention", "confirmed", "info", "not_checked"]
    # job page on the company's domain (confirmed), redirected there (info), plain http and a Gmail address (attention)
    mixed = checks(final_url="http://jobs.acme.com/1", requested_url="https://s.example-links.com/x", redirect_count=1,
                   structured_job_data_found=True, company_website="acme.com", recruiter_email="x@gmail.com")
    statuses = [c["status"] for c in mixed]
    check("a mixed result contains every kind of status", set(statuses) >= {"attention", "confirmed", "info"}, str(statuses))
    check("ordering puts attention first, then confirmed, info, not_checked", statuses == sorted(statuses, key=order.index), str(statuses))
    unchecked = [c["status"] for c in checks(final_url="https://a.example-firm.com/x", recruiter_email="x@a.example-firm.com")]
    check("not_checked items come last", unchecked[-1] == "not_checked" and unchecked == sorted(unchecked, key=order.index), str(unchecked))
    check("an empty request produces no checks and does not crash", run_verification() == {"checks": []})
    check("the same input always gives the same output", run_verification(**sample_inputs[1]) == run_verification(**sample_inputs[1]))
    for hostile in [dict(company_website="x" * 100_000), dict(recruiter_email="a@" + "b." * 5000 + "com"), dict(final_url="https://" + "a." * 300 + "com/"),
                    dict(company_website=5, recruiter_email=["a"]), dict(final_url="not a url", requested_url="also not")]:
        try:
            run_verification(**hostile)
            survived = True
        except Exception as error:
            survived = False
            print("      raised", type(error).__name__, error)
        check(f"hostile or garbled input does not crash ({list(hostile)[0]})", survived)


def test_independence_and_offline():
    source = Path(verification.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    check("verification imports only the standard library and tldextract (no model, scanner, importer, HTTP client or AI package)",
          imported <= {"re", "dataclasses", "urllib", "tldextract"}, str(sorted(imported)))
    check("verification does not read test.csv", "test.csv" not in source)
    check("tldextract is configured to use only its bundled data (no download, no disk cache)",
          "suffix_list_urls=()" in source and "cache_dir=None" in source)

    original = (socket.socket, socket.getaddrinfo, socket.create_connection)
    socket.socket, socket.getaddrinfo, socket.create_connection = _no_network, _no_network, _no_network
    try:
        try:
            run_verification(final_url="https://jobs.company.com/x", requested_url="https://short.example.com/x", redirect_count=1,
                             structured_job_data_found=True, company_website="https://never-opened.example-firm.org",
                             recruiter_email="hr@cornpany.com")
            registered_domain("brand-new.unknown-domain.co.uk")
            offline = True
        except NetworkAttempt:
            offline = False
    finally:
        socket.socket, socket.getaddrinfo, socket.create_connection = original
    check("with every network call disabled the checks still run (no download, no website is opened)", offline)


def main():
    test_domain_normalization()
    test_company_website_check()
    test_ats_detection()
    test_recruiter_email_checks()
    test_lookalike_domains()
    test_punycode()
    test_https_redirect_structured()
    test_result_model()
    test_independence_and_offline()
    print(f"\n{sum(results)} of {len(results)} checks passed")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
