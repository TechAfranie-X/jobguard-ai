"""Simple manual test script for the JobGuard API (API functionality only, NOT ML evaluation).

Run from the project root:   python -m backend.test_api

It uses hand-written demonstration postings only. test.csv and the other datasets are never read.
The example predictions are printed for you to look at; they are not used to judge or tune the model.
"""

import logging
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from backend import main as main_module
from backend import model_service, url_importer, verification
from backend.demo_pages import build_demo_web
from backend.intake_parser import parse_posting
from backend.main import app
from backend.model_service import MAX_LENGTH, THRESHOLD, ModelService, build_combined_text, verify_model_directory
from backend.schemas import MAX_FIELD_CHARS, STRUCTURED_FIELDS
from src.preprocessing import create_combined_text

# ---- Demonstration postings (same style as the examples used during model development) ----
PROFESSIONAL = {
    "title": "Software Engineer",
    "company_profile": "Northwind Analytics is a data company serving hospitals and universities. "
                       "We build tools that help researchers understand their data.",
    "description": "We are looking for a software engineer to join our platform team. You will design, build and "
                   "test backend services in Python, review code with teammates, and participate in on-call rotation.",
    "requirements": "Bachelor's degree in computer science or equivalent experience. 3 years of Python and SQL. "
                    "Experience with automated testing and version control.",
    "benefits": "Health, dental and vision insurance, 401(k) match, paid vacation.",
}
SUSPICIOUS = {
    "title": "Work From Home - Earn $5000 Weekly!!!",
    "company_profile": "",
    "description": "No experience needed! Earn thousands every week from home. Limited spots. Send your full name, "
                   "address, date of birth and bank account details to start immediately. "
                   "A small registration fee is required.",
    "requirements": "Must have a bank account and be able to pay the registration fee.",
    "benefits": "",
}
SHORT = {"title": "Data Entry Clerk", "description": "Data entry. Work from home. Apply now."}

# The same two postings as ONE pasted text (what a user would copy from a job site). The intake parser must turn
# each of them back into exactly the five fields above.
PROFESSIONAL_RAW = """Software Engineer

About Us
Northwind Analytics is a data company serving hospitals and universities. We build tools that help researchers understand their data.

About the Role
We are looking for a software engineer to join our platform team. You will design, build and test backend services in Python, review code with teammates, and participate in on-call rotation.

Qualifications
Bachelor's degree in computer science or equivalent experience. 3 years of Python and SQL. Experience with automated testing and version control.

What We Offer
Health, dental and vision insurance, 401(k) match, paid vacation."""
SUSPICIOUS_RAW = """Work From Home - Earn $5000 Weekly!!!

Job Description
No experience needed! Earn thousands every week from home. Limited spots. Send your full name, address, date of birth and bank account details to start immediately. A small registration fee is required.

Requirements
Must have a bank account and be able to pay the registration fee."""
NO_HEADINGS_RAW = "We are hiring now. Work from home and earn cash daily. Send your details to apply."

# Milestone 13 scenarios for the warning-sign scanner (hand-written, not real jobs).
_SUPPORT_HEAD = "Customer Support Representative\n\nAbout Us\nExample Co. provides billing software to small businesses.\n\n"
UPFRONT_ONLY_RAW = _SUPPORT_HEAD + ("Job Description\nAnswer customer questions by email and chat. A $75 registration fee is "
                                    "required before your first day.\n\nRequirements\nGood written English.")
SENSITIVE_ONLY_RAW = _SUPPORT_HEAD + ("Job Description\nAnswer customer questions by email and chat. Please send a copy of "
                                      "your passport and Social Security number with your application.\n\n"
                                      "Requirements\nGood written English.")
NEGATED_FEE_RAW = _SUPPORT_HEAD + ("Job Description\nAnswer customer questions by email and chat.\n\nRequirements\n"
                                   "Good written English.\n\nBenefits\nPaid vacation. There is no application fee, and no "
                                   "payment is ever required.")
HIGH_PAY_TECH_RAW = """Staff Software Engineer

About Us
Harbor Payments builds payment tools for online merchants.

About the Role
Integrate PayPal, Stripe and Zelle APIs into our checkout platform. Salary: $180,000 - $220,000 per year. Company-provided laptop and equipment.

Qualifications
8 years of backend engineering experience.

What We Offer
Equity, health insurance, and expense reimbursement under company policy."""
REMOTE_NORMAL_RAW = """Customer Support Specialist (Remote)

About the Role
This is a fully remote, work from home position. You will answer customer tickets, document solutions, and join a weekly team meeting. Hybrid options are available in our Austin office.

Qualifications
2 years of customer support experience.

What We Offer
Paid vacation and a home-office stipend."""
GMAIL_RAW = """Office Assistant

About the Role
Organize schedules and answer phones.

How to Apply
Send your resume to hiring.manager@gmail.com."""

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))


def timed_post(client, payload):
    started = time.perf_counter()
    response = client.post("/predict", json=payload)
    return response, (time.perf_counter() - started) * 1000


GOOD_URL = "https://careers.northwind-analytics.com/jobs/software-engineer"
SHORT_URL = "https://short.example-links.com/r/3fK9"
MODEL_FIELDS = ("prediction", "label", "fraud_probability", "fraud_percentage", "model", "threshold", "disclaimer")


def milestone14_checks(client, service, original_predict):
    """URL import and verification (Milestone 14). The network is replaced by canned pages (backend/demo_pages.py);
    the DistilBERT model, the scanner and the verification code are the real ones."""
    web = build_demo_web()
    url_importer.use_fake_network_for_demo(resolver=web.resolver, transport=web.transport())
    try:
        # ---- /import-url never runs the model ----
        def forbid_model(text):
            raise AssertionError("the model must not run inside /import-url")
        service.predict = forbid_model
        response = client.post("/import-url", json={"url": GOOD_URL, "company_website": "https://northwind-analytics.com",
                                                    "recruiter_email": "recruiter@northwind-analytics.com"})
        service.predict = original_predict
        body = response.json()
        check("POST /import-url imports a controlled company page without calling the model",
              response.status_code == 200 and body["imported"] is True and body["reason"] is None)
        check("the import response has source, raw_posting, the five extracted fields, checks and timings",
              set(body) == {"imported", "message", "reason", "source", "raw_posting", "extracted_fields", "checks", "timings_ms"}
              and set(body["source"]) == {"requested_url", "final_url", "source_domain", "redirect_count", "https",
                                          "structured_job_data_found", "page_title", "company_name"}
              and set(body["extracted_fields"]) >= set(STRUCTURED_FIELDS)
              and set(body["timings_ms"]) == {"fetch", "html_extract", "intake_parse", "verification"})
        check("source: public company domain, HTTPS, no redirect, JobPosting data found, employer named by the page",
              body["source"]["source_domain"] == "careers.northwind-analytics.com" and body["source"]["https"] is True
              and body["source"]["redirect_count"] == 0 and body["source"]["structured_job_data_found"] is True
              and body["source"]["company_name"] == "Northwind Analytics")
        raw = body["raw_posting"]
        check("the imported text is the posting (title, requirements and benefits sorted by the existing parser)",
              body["extracted_fields"]["title"] == "Software Engineer" and "Python and SQL" in body["extracted_fields"]["requirements"]
              and "401(k)" in body["extracted_fields"]["benefits"] and body["extracted_fields"] == parse_posting(raw).to_dict())
        by_id = {c["id"]: c for c in body["checks"]}
        check("verification: job host MATCH, recruiter email MATCH, HTTPS, structured data",
              by_id["job_host"]["result"] == "MATCH" and by_id["recruiter_email"]["result"] == "MATCH"
              and by_id["https"]["result"] == "HTTPS" and by_id["structured_data"]["result"] == "JOB_POSTING_DATA")
        check("verification checks have only the four allowed statuses and no score field",
              {c["status"] for c in body["checks"]} <= {"confirmed", "attention", "info", "not_checked"}
              and not any(word in str(body.keys()) for word in ("score", "percent", "legitimacy", "trust")))

        # ---- URL -> import -> /predict: exactly ONE DistilBERT inference for the completed analysis ----
        sent_to_model = []
        service.predict = lambda text: (sent_to_model.append(text), original_predict(text))[1]
        client.post("/import-url", json={"url": GOOD_URL})
        flow = client.post("/predict", json={"raw_posting": raw})
        service.predict = original_predict
        flow_body = flow.json()
        check("import + predict make exactly ONE DistilBERT inference, on the unchanged parser output",
              len(sent_to_model) == 1 and sent_to_model == [build_combined_text(**parse_posting(raw).fields())], f"{len(sent_to_model)} calls")
        check("the prediction for an imported page has the normal fields plus signals",
              flow.status_code == 200 and set(flow_body) == set(MODEL_FIELDS) | {"signals", "signal_count"})

        # ---- verification metadata cannot change the model's input or output ----
        variants = [
            {"url": GOOD_URL},
            {"url": GOOD_URL, "company_website": "https://other-company.org", "recruiter_email": "someone@gmail.com"},
            {"url": GOOD_URL, "company_website": "xn--80ak6aa92e.com", "recruiter_email": "x@cornpany.com"},
        ]
        seen_inputs, seen_outputs, seen_raw = [], [], []
        for payload in variants:
            imported = client.post("/import-url", json=payload).json()
            sent_to_model = []
            service.predict = lambda text, _record=sent_to_model: (_record.append(text), original_predict(text))[1]
            predicted = client.post("/predict", json={"raw_posting": imported["raw_posting"]}).json()
            service.predict = original_predict
            seen_raw.append(imported["raw_posting"])
            seen_inputs.append(tuple(sent_to_model))
            seen_outputs.append(({k: predicted[k] for k in MODEL_FIELDS}, predicted["signals"]))
        check("identical imported text under three different sets of verification details: same posting text",
              len(set(seen_raw)) == 1)
        check("...same text sent to DistilBERT, same fraud probability, label, threshold and warning signs",
              len(set(seen_inputs)) == 1 and all(output == seen_outputs[0] for output in seen_outputs))
        check("the three variants did produce different verification checks (so the test is not vacuous)",
              client.post("/import-url", json=variants[0]).json()["checks"] != client.post("/import-url", json=variants[1]).json()["checks"])
        sent_to_model = []
        service.predict = lambda text: (sent_to_model.append(text), original_predict(text))[1]
        with_extras = client.post("/predict", json={"raw_posting": raw, "company_website": "https://evil.test", "recruiter_email": "a@gmail.com"})
        service.predict = original_predict
        check("verification details sent to /predict are ignored: same model input and same prediction",
              with_extras.status_code == 200 and sent_to_model == list(seen_inputs[0])
              and {k: with_extras.json()[k] for k in MODEL_FIELDS} == seen_outputs[0][0])
        check("the locked decision rule is untouched by the URL flow (threshold 0.5, max_length 256)", THRESHOLD == 0.5 and MAX_LENGTH == 256)

        # ---- a suspicious page behind a short link: redirect to another domain, plain HTTP, personal email ----
        suspicious = client.post("/import-url", json={"url": SHORT_URL, "company_website": "https://northwind-analytics.com",
                                                      "recruiter_email": "quickhire.jobs@gmail.com"}).json()
        ids = {c["id"]: c for c in suspicious["checks"]}
        check("short link: redirect noticed, final page is plain HTTP on another domain",
              suspicious["imported"] and suspicious["source"]["redirect_count"] == 1
              and suspicious["source"]["source_domain"] == "quick-hire-jobs.com" and suspicious["source"]["https"] is False
              and ids["redirect"]["result"] == "REDIRECTED" and ids["https"]["result"] == "HTTP")
        check("short link: job host differs from the supplied company, recruiter email is personal",
              ids["job_host"]["result"] == "DIFFERENT_DOMAIN" and ids["recruiter_email"]["result"] == "PERSONAL_EMAIL")
        check("attention checks come first", suspicious["checks"][0]["status"] == "attention")
        sent_to_model = []
        service.predict = lambda text: (sent_to_model.append(text), original_predict(text))[1]
        suspicious_prediction = client.post("/predict", json={"raw_posting": suspicious["raw_posting"]}).json()
        service.predict = original_predict
        found = {s["id"] for s in suspicious_prediction["signals"]}
        check("the scanner reads the imported page text (fee, sensitive information, personal email) and the model ran once",
              {"upfront_payment", "sensitive_info", "personal_email"} <= found and len(sent_to_model) == 1, str(sorted(found)))

        # ---- graceful failures: a normal answer, never a stack trace, and unsafe addresses are never requested ----
        requests_before = len(web.requests)
        for unsafe in ["http://127.0.0.1/secret-path-123", "http://169.254.169.254/latest/meta-data/", "http://localhost:8000/health",
                       "http://[::1]/", "http://10.0.0.5/admin", "file:///etc/passwd", "https://user:pw@careers.northwind-analytics.com/x"]:
            failed = client.post("/import-url", json={"url": unsafe})
            fb = failed.json()
            check(f"unsafe URL {unsafe[:44]!r}: a normal 'could not import' answer, nothing fetched",
                  failed.status_code == 200 and fb["imported"] is False and fb["raw_posting"] is None and fb["source"] is None
                  and fb["checks"] == [] and fb["message"] == "We couldn't import this page automatically. Paste the job posting instead."
                  and fb["reason"] in ("blocked_address", "invalid_url") and "Traceback" not in failed.text)
        check("none of the unsafe URLs reached the (fake) network", len(web.requests) == requests_before)
        for url, reason in [("https://www.job-board-example.com/view/991", "blocked_by_site"), ("https://spa.job-board-example.org/jobs/55", "no_content"),
                            ("https://careers.northwind-analytics.com/jobs/missing", "not_found")]:
            fb = client.post("/import-url", json={"url": url}).json()
            check(f"{url.split('/')[2]}: import stops gracefully ({reason})", fb["imported"] is False and fb["reason"] == reason
                  and fb["message"].endswith("Paste the job posting instead."))
        original_import = main_module.import_job_url
        main_module.import_job_url = lambda url: (_ for _ in ()).throw(RuntimeError("simulated crash with /secret/path"))
        crashed = client.post("/import-url", json={"url": GOOD_URL})
        main_module.import_job_url = original_import
        check("an unexpected importer error still gives a clean 'could not import' answer without details",
              crashed.status_code == 200 and crashed.json()["imported"] is False and "simulated" not in crashed.text
              and "Traceback" not in crashed.text)

        # ---- request validation ----
        for name, payload in {"no body fields": {}, "blank url": {"url": ""}, "whitespace url": {"url": "   "},
                              "url too long": {"url": "https://a.com/" + "x" * 2100}, "url of the wrong type": {"url": 5},
                              "company website too long": {"url": GOOD_URL, "company_website": "x" * 2100},
                              "recruiter email too long": {"url": GOOD_URL, "recruiter_email": "x" * 400}}.items():
            response = client.post("/import-url", json=payload)
            check(f"/import-url rejects invalid input with 422: {name}", response.status_code == 422 and "Traceback" not in response.text)
        blank = client.post("/import-url", json={"url": GOOD_URL, "company_website": "  ", "recruiter_email": ""}).json()
        check("blank optional details count as not given (no recruiter check, job host not compared)",
              "recruiter_email" not in {c["id"] for c in blank["checks"]} and {c["id"]: c for c in blank["checks"]}["job_host"]["result"] == "NOT_CHECKED")
        scheme_less = client.post("/import-url", json={"url": "careers.northwind-analytics.com/jobs/software-engineer"}).json()
        check("a link pasted without https:// still works", scheme_less["imported"] is True and scheme_less["source"]["https"] is True)

        # ---- privacy: nothing about the request is logged or kept ----
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Capture()
        logging.getLogger().addHandler(handler)              # root logger: also sees the HTTP client library's own logs
        client.post("/import-url", json={"url": "https://careers.northwind-analytics.com/jobs/missing-secret-987"})
        client.post("/import-url", json={"url": "http://127.0.0.1/secret-path-123", "recruiter_email": "private.person@gmail.com",
                                         "company_website": "https://private-company-name.test"})
        main_module.import_job_url = lambda url: (_ for _ in ()).throw(RuntimeError("boom"))
        client.post("/import-url", json={"url": GOOD_URL, "recruiter_email": "private.person@gmail.com"})
        main_module.import_job_url = original_import
        logging.getLogger().removeHandler(handler)
        joined = " ".join(records)
        check("the server log contains no URL, path, email address or company name from the request (HTTP client logs included)",
              records and not any(secret in joined for secret in ("secret-path-123", "missing-secret-987", "private.person",
                                                                  "private-company-name", "northwind")), joined[:160])
        storage_words = ("sqlite3", "sqlalchemy", "shelve", "pickle", "open(", ".write(", "mkdir", "tempfile", "redis", "pymongo")
        sources = {name: Path(module.__file__).read_text() for name, module in
                   {"main": main_module, "url_importer": url_importer, "verification": verification}.items()}
        check("the request-handling code has no database or file storage (JobGuard does not store analyses)",
              not any(word in text for text in sources.values() for word in storage_words),
              str([(n, w) for n, t in sources.items() for w in storage_words if w in t]))

        preflight = client.options("/import-url", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                                           "Access-Control-Request-Headers": "content-type"})
        check("CORS preflight for /import-url from the Vite dev server is allowed",
              preflight.status_code == 200 and preflight.headers.get("access-control-allow-origin") == "http://localhost:5173")
        check("the API version is 1.3.0", app.version == "1.3.0")
    finally:
        url_importer.use_fake_network_for_demo()          # back to the real network
        service.predict = original_predict


def main():
    with TestClient(app) as client:        # "with" runs the startup/shutdown (lifespan) like a real server
        service = app.state.model_service

        # ---- basic routes ----
        response = client.get("/")
        check("GET / returns the API status", response.status_code == 200 and response.json() ==
              {"name": "JobGuard AI API", "status": "running"}, str(response.json()))

        health = client.get("/health").json()
        check("GET /health reports a loaded DistilBERT model",
              health["status"] == "ok" and health["model_loaded"] is True and health["model"] == "DistilBERT"
              and health["device"] in ("cuda", "mps", "cpu"), str(health))
        check("GET /health does not expose filesystem paths", "/" not in str(health))
        check("/docs (Swagger UI) is served", client.get("/docs").status_code == 200)
        check("/openapi.json is served", client.get("/openapi.json").status_code == 200)

        # ---- predictions ----
        # The Milestone 7-12 response fields, plus the scanner's two fields (added in Milestone 13).
        expected_keys = {"prediction", "label", "fraud_probability", "fraud_percentage", "model", "threshold", "disclaimer",
                         "signals", "signal_count"}
        timings = []
        for name, payload in [("professional", PROFESSIONAL), ("suspicious", SUSPICIOUS), ("short", SHORT)]:
            response, milliseconds = timed_post(client, payload)
            body = response.json()
            timings.append(milliseconds)
            check(f"POST /predict ({name}) returns 200 with all response fields",
                  response.status_code == 200 and set(body) == expected_keys)
            probability = body["fraud_probability"]
            check(f"POST /predict ({name}) is consistent with the locked 0.5 threshold",
                  0 <= probability <= 1 and body["threshold"] == 0.5 == THRESHOLD
                  and (body["prediction"] == "fraudulent") == (probability >= 0.5)
                  and body["label"] == ("Potentially Fraudulent" if probability >= 0.5 else "Likely Legitimate")
                  and abs(body["fraud_percentage"] - probability * 100) < 0.01 and body["model"] == "DistilBERT")
            print(f"      -> {name}: {body['label']} | fraud_probability {body['fraud_probability']} "
                  f"| {milliseconds:.0f} ms (including HTTP handling)")

        # Optional fields may be omitted or null
        response = client.post("/predict", json={"title": "Nurse", "description": "Care for patients.", "benefits": None})
        check("optional fields may be omitted or null", response.status_code == 200)

        # ---- Milestone 12: one pasted posting (raw_posting) goes through the intake parser ----
        sent_to_model = []
        original_predict = service.predict

        def recording_predict(text):
            sent_to_model.append(text)
            return original_predict(text)

        service.predict = recording_predict
        raw_results = {}
        for name, raw_text, structured in [("professional", PROFESSIONAL_RAW, PROFESSIONAL),
                                           ("suspicious", SUSPICIOUS_RAW, SUSPICIOUS)]:
            sent_to_model.clear()
            raw_response, raw_ms = timed_post(client, {"raw_posting": raw_text})
            structured_response = client.post("/predict", json=structured)
            raw_body, structured_body = raw_response.json(), structured_response.json()
            raw_results[name] = raw_body
            check(f"raw_posting ({name}): returns 200 with the unchanged response fields",
                  raw_response.status_code == 200 and set(raw_body) == expected_keys)
            expected_text = build_combined_text(**{field: structured.get(field, "") for field in STRUCTURED_FIELDS})
            check(f"raw_posting ({name}): the model receives exactly the training-format text built from the "
                  "five separate fields", len(sent_to_model) == 2 and sent_to_model[0] == sent_to_model[1] == expected_text)
            check(f"raw_posting ({name}): same prediction and probability as the structured request",
                  raw_body == structured_body)
            print(f"      -> raw {name}: {raw_body['label']} | fraud_probability {raw_body['fraud_probability']} "
                  f"| {raw_ms:.0f} ms (including parsing and HTTP handling)")
        check("raw professional posting is Likely Legitimate and raw suspicious posting is Potentially Fraudulent "
              "(demonstration examples, not an evaluation)",
              raw_results["professional"]["prediction"] == "legitimate" and raw_results["suspicious"]["prediction"] == "fraudulent")

        sent_to_model.clear()
        response = client.post("/predict", json={"raw_posting": NO_HEADINGS_RAW})
        check("a posting with no headings is still analyzed, and ALL of its text reaches the model",
              response.status_code == 200 and len(sent_to_model) == 1
              and sent_to_model[0] == build_combined_text("", "", NO_HEADINGS_RAW, "", ""), repr(sent_to_model[:1]))
        check("exactly one model prediction is made per request", len(sent_to_model) == 1)
        sent_to_model.clear()
        edited = {**PROFESSIONAL, "requirements": "Edited requirements text."}
        client.post("/predict", json=edited)
        check("edited fields (structured request) are sent to the model as given",
              sent_to_model == [build_combined_text(edited["title"], edited["company_profile"], edited["description"],
                                                    "Edited requirements text.", edited["benefits"])])
        service.predict = original_predict

        # ---- Milestone 13: the warning-sign scanner runs NEXT TO the model, never inside it ----
        scenarios = {
            "1 clean professional posting": (PROFESSIONAL_RAW, set(), True),
            "2 suspicious multi-signal posting": (SUSPICIOUS_RAW, {"upfront_payment", "sensitive_info", "unrealistic_pay",
                                                                  "urgency"}, False),
            "3 upfront payment only": (UPFRONT_ONLY_RAW, {"upfront_payment"}, True),
            "4 sensitive information only": (SENSITIVE_ONLY_RAW, {"sensitive_info"}, True),
            "5 negated fee statement": (NEGATED_FEE_RAW, set(), True),
            "6 legitimate high-paying technical job": (HIGH_PAY_TECH_RAW, set(), True),
            "7 remote job with normal responsibilities": (REMOTE_NORMAL_RAW, set(), True),
            "8 personal Gmail recruiter address": (GMAIL_RAW, {"personal_email"}, True),
        }
        scenario_keys = expected_keys | {"signals", "signal_count"}
        for name, (raw_text, expected_ids, exact) in scenarios.items():
            sent_to_model = []
            service.predict = lambda text, _record=sent_to_model: (_record.append(text), original_predict(text))[1]
            response = client.post("/predict", json={"raw_posting": raw_text})
            service.predict = original_predict
            body = response.json()
            found = {signal["id"] for signal in body.get("signals", [])}
            check(f"scenario {name}: 200 with the prediction fields plus signals and signal_count",
                  response.status_code == 200 and set(body) == scenario_keys)
            check(f"scenario {name}: warning signs found = {sorted(expected_ids) or 'none'}",
                  (found == expected_ids) if exact else expected_ids <= found, f"found {sorted(found)}")
            check(f"scenario {name}: signal_count matches the list and every quote is verbatim from the pasted text",
                  body["signal_count"] == len(body["signals"])
                  and all(quote in raw_text for signal in body["signals"]
                          for quote in [signal["evidence"]] + signal["more_evidence"]))
            check(f"scenario {name}: DistilBERT predicted exactly once, on the unchanged parser output",
                  sent_to_model == [build_combined_text(**parse_posting(raw_text).fields())], f"{len(sent_to_model)} calls")

        # The scanner cannot influence the model: switching it off changes nothing about the prediction.
        with_scanner = client.post("/predict", json={"raw_posting": SUSPICIOUS_RAW}).json()
        original_scan = main_module.scan_job_signals
        main_module.scan_job_signals = lambda *args, **kwargs: {"signals": [], "signal_count": 0}
        without_scanner = client.post("/predict", json={"raw_posting": SUSPICIOUS_RAW}).json()
        main_module.scan_job_signals = original_scan
        model_fields = ("prediction", "label", "fraud_probability", "fraud_percentage", "model", "threshold", "disclaimer")
        check("prediction, probability and label are identical with the scanner on and off",
              {k: with_scanner[k] for k in model_fields} == {k: without_scanner[k] for k in model_fields}
              and with_scanner["signal_count"] > 0 == without_scanner["signal_count"])
        check("the scanner returns no second score or risk level",
              not any(word in key for key in with_scanner for word in ("signal_score", "signal_risk", "safety")))

        # A request made of separate fields is scanned too (the text is the non-empty fields joined with blank lines).
        field_request = {**PROFESSIONAL, "description": PROFESSIONAL["description"] + " A $75 registration fee is required."}
        field_body = client.post("/predict", json=field_request).json()
        joined = "\n\n".join(field_request[name] for name in STRUCTURED_FIELDS if field_request.get(name))
        check("a five-field request is scanned as well, with verbatim quotes",
              [s["id"] for s in field_body["signals"]] == ["upfront_payment"]
              and all(q in joined for s in field_body["signals"] for q in [s["evidence"]] + s["more_evidence"]))
        plain_body = client.post("/predict", json=PROFESSIONAL).json()
        check("the original five-field request still works and reports zero warning signs for a clean posting",
              plain_body["signal_count"] == 0 and plain_body["signals"] == [])

        # ---- Milestone 14: job URL import and verification checks ----
        milestone14_checks(client, service, original_predict)

        # ---- /extract: the same parser, no model ----
        service.predict = lambda text: (_ for _ in ()).throw(AssertionError("the model must not run for /extract"))
        response = client.post("/extract", json={"raw_posting": PROFESSIONAL_RAW})
        service.predict = original_predict
        extracted = response.json()
        check("POST /extract returns the five fields and the report without calling the model",
              response.status_code == 200 and set(extracted) == {"title", "company_profile", "description", "requirements",
              "benefits", "detected_sections", "missing_sections", "fallback_used"})
        check("POST /extract finds the sections of the professional example",
              extracted["title"] == PROFESSIONAL["title"] and extracted["company_profile"] == PROFESSIONAL["company_profile"]
              and extracted["description"] == PROFESSIONAL["description"]
              and extracted["requirements"] == PROFESSIONAL["requirements"] and extracted["benefits"] == PROFESSIONAL["benefits"]
              and extracted["missing_sections"] == [])
        check("POST /extract gives the same answer every time",
              client.post("/extract", json={"raw_posting": PROFESSIONAL_RAW}).json() == extracted)
        check("POST /extract rejects blank text with 422", client.post("/extract", json={"raw_posting": "  \n "}).status_code == 422)

        # ---- input validation ----
        # Since Milestone 12 a posting only needs SOME text: the title may be empty (the intake parser does not
        # invent a title), so a request with a blank title but a description is accepted.
        accepted_requests = {
            "blank title": {**PROFESSIONAL, "title": ""},
            "blank description": {**PROFESSIONAL, "description": ""},
            "missing title": {k: v for k, v in PROFESSIONAL.items() if k != "title"},
            "only one field": {"requirements": "Python"},
        }
        for name, payload in accepted_requests.items():
            check(f"structured request with some text is accepted: {name}", client.post("/predict", json=payload).status_code == 200)
        bad_requests = {
            "all fields blank": {"title": " ", "description": "", "requirements": "\n"},
            "empty object": {},
            "title and description both whitespace-only": {"title": "   \n ", "description": "   "},
            "wrong type": {**PROFESSIONAL, "title": 123},
            "oversized field": {**PROFESSIONAL, "benefits": "a" * (MAX_FIELD_CHARS + 1)},
            "blank raw_posting": {"raw_posting": "   \n "},
            "empty raw_posting": {"raw_posting": ""},
            "raw_posting of the wrong type": {"raw_posting": 123},
            "oversized raw_posting": {"raw_posting": "a" * (MAX_FIELD_CHARS + 1)},
            "raw_posting together with separate fields": {"raw_posting": PROFESSIONAL_RAW, "title": "Nurse"},
        }
        for name, payload in bad_requests.items():
            response = client.post("/predict", json=payload)
            check(f"invalid request rejected with 422: {name}", response.status_code == 422 and "Traceback" not in response.text)
        check("a request that is not JSON at all is rejected", client.post("/predict", content="hello").status_code == 422)

        # ---- the text given to DistilBERT matches the training format ----
        built = build_combined_text("T", "C", "D", "R", "B")
        check("combined_text uses the exact training format", built == "TITLE: T\nCOMPANY PROFILE: C\nDESCRIPTION: D\n"
              "REQUIREMENTS: R\nBENEFITS: B", repr(built))
        frame = pd.DataFrame([PROFESSIONAL])
        check("build_combined_text equals src.preprocessing.create_combined_text",
              build_combined_text(**{k: PROFESSIONAL[k] for k in PROFESSIONAL}) == create_combined_text(frame).iloc[0])
        check("empty optional fields keep their labels (as for missing values in training)",
              build_combined_text("T", "", "D", "", "") == "TITLE: T\nCOMPANY PROFILE: \nDESCRIPTION: D\nREQUIREMENTS: \nBENEFITS: ")
        padded = service.tokenizer("  TITLE: Nurse\n  ", truncation=True, max_length=MAX_LENGTH)["input_ids"]
        trimmed = service.tokenizer("TITLE: Nurse", truncation=True, max_length=MAX_LENGTH)["input_ids"]
        check("trimming surrounding whitespace does not change the token IDs", padded == trimmed)

        # ---- tokenization limits ----
        huge_text = build_combined_text("T", "C", "word " * 5000, "R", "B")
        ids = service.tokenizer(huge_text, truncation=True, max_length=MAX_LENGTH, padding=True, return_tensors="pt",
                                return_token_type_ids=False)["input_ids"]
        check("very long postings are truncated by the tokenizer to max_length=256", ids.shape[1] == MAX_LENGTH == 256)
        response = client.post("/predict", json={**PROFESSIONAL, "description": "word " * 5000})
        check("a very long posting is still accepted and scored", response.status_code == 200)

        # ---- model loading behaviour ----
        check("the model was loaded exactly once, at startup", ModelService.load_count == 1, f"load_count={ModelService.load_count}")
        check("every request reused the same loaded model", app.state.model_service is service)
        check("no XGBoost (or other classic-ML model) was imported", "xgboost" not in sys.modules)
        check("the model lives in eval (inference) mode", not service.model.training)
        check("the model files were read from the local models/distilbert/ folder",
              "distilbert" in str(service.model.name_or_path))

        # ---- errors never leak stack traces or turn into 'legitimate' ----
        original_predict = service.predict
        service.predict = lambda text: (_ for _ in ()).throw(RuntimeError("simulated inference failure"))
        response = client.post("/predict", json=PROFESSIONAL)
        service.predict = original_predict
        check("an inference error returns a plain 500, not a prediction",
              response.status_code == 500 and "prediction" not in response.json())
        check("the 500 response contains no stack trace or internal details",
              "Traceback" not in response.text and "simulated" not in response.text)

        # ---- CORS for the future React/Vite frontend ----
        preflight = client.options("/predict", headers={"Origin": "http://localhost:5173",
                                                         "Access-Control-Request-Method": "POST",
                                                         "Access-Control-Request-Headers": "content-type"})
        check("CORS preflight from http://localhost:5173 is allowed",
              preflight.status_code == 200 and preflight.headers.get("access-control-allow-origin") == "http://localhost:5173")
        check("CORS for http://127.0.0.1:5173 is allowed",
              client.get("/health", headers={"Origin": "http://127.0.0.1:5173"}).headers.get("access-control-allow-origin")
              == "http://127.0.0.1:5173")
        check("CORS for other origins is not allowed",
              "access-control-allow-origin" not in client.get("/health", headers={"Origin": "http://evil.example"}).headers)

    # ---- startup failure when the trained weights are missing (done outside the server, in a temporary folder) ----
    with tempfile.TemporaryDirectory() as folder:
        for name in ["config.json", "tokenizer.json", "tokenizer_config.json"]:
            (Path(folder) / name).write_text("{}")
        try:
            verify_model_directory(folder)
            check("missing model.safetensors is detected at startup", False)
        except FileNotFoundError as error:
            check("missing model.safetensors is detected at startup with a clear message", "model.safetensors" in str(error))
    check("the locked settings are unchanged (max_length 256, threshold 0.5)", model_service.MAX_LENGTH == 256 and THRESHOLD == 0.5)

    print(f"\n{sum(results)} of {len(results)} checks passed")
    if len(timings) == 3:
        print("Request times in ms (first request includes one-time warm-up): ", [round(t) for t in timings])
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
