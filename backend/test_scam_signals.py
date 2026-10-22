"""Tests for the Job Scam Signal Scanner (backend/scam_signals.py).

Run from the project root:   python -m backend.test_scam_signals

Only hand-written text is used. No model is loaded, no network is used, and test.csv is never read.
For every rule there is a positive example, a control (ordinary text that must NOT be flagged), and, where it makes
sense, a negated example ("No application fee ..."). A separate section proves that every quote the scanner shows is
really present in the text it was given.
"""

import ast
import sys
import time
from pathlib import Path

from backend import scam_signals
from backend.scam_signals import MAX_EVIDENCE_CHARS, RULES, SEVERITIES, scan_job_signals

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))


def ids(text):
    return [signal["id"] for signal in scan_job_signals(text)["signals"]]


# ---------------------------------------------------------------------------------------------------------------
# Per-rule examples: (rule id, [must be flagged], [must NOT be flagged: ordinary text], [must NOT be flagged: negated])
# ---------------------------------------------------------------------------------------------------------------

RULE_CASES = [
    ("upfront_payment",
     ["Pay a $50 application fee.",
      "A $75 registration fee is required.",
      "You must pay a training fee before starting.",
      "Pay before starting.",
      "Applicants must purchase a starter kit to begin."],
     ["Competitive pay and paid training.",
      "We provide all equipment and training."],
     ["No application fee is required.",
      "There is no registration or application fee.",
      "We never charge a training fee.",
      "Application fee: none.",
      "Training costs are covered by the company.",
      "Do not pay any fee to apply."]),
    ("fake_check",
     ["We will send you a check to purchase equipment.",
      "Deposit the check and send the remaining balance to our vendor.",
      "We will send a check. Deposit it and purchase your laptop."],
     ["Company provides a laptop.",
      "Equipment provided by the employer.",
      "Please check the box below to confirm your email.",
      "We run a standard background check before your start date."],
     ["Never deposit a check from an employer and send money back."]),
    ("purchase_reimbursement",
     ["Buy your laptop and we will reimburse you.",
      "We will reimburse you after you purchase the equipment."],
     ["Expenses are reimbursed according to company policy.",
      "Company will reimburse approved travel expenses.",
      "Company provides a laptop."],
     []),
    ("sensitive_info",
     ["Send your full name, address, date of birth and bank account details to start immediately.",
      "Please email a copy of your passport and Social Security number.",
      "Reply with your routing number and account number."],
     ["Valid driver's license required.",
      "Process credit card payments and send receipts to customers.",
      "Must have a bank account for direct deposit.",
      "Upload your resume and a passport-size photo."],
     ["We will never ask for your bank account details.",
      "After you accept the offer, we will request your Social Security number for payroll."]),
    ("payment_method",
     ["Send payment through PayPal.",
      "Buy gift cards and send us the codes.",
      "Please send $200 by Bitcoin to start.",
      "You will receive payments from clients via Zelle and forward the funds to us."],
     ["Experience with PayPal APIs.",
      "Integrate Stripe, PayPal and Zelle into our checkout.",
      "You will design systems that receive payments and send funds to merchants via wire transfer.",
      "Customers buy gift cards at the register."],
     ["Do not send money by gift card.",
      "Never pay with Bitcoin or gift cards."]),
    ("unrealistic_pay",
     ["Earn $5,000 weekly, no experience, work one hour daily.",
      "Earn $5000 Weekly. No experience needed!",
      "Make $800 a day working one hour."],
     ["Competitive salary: $180,000",
      "Senior engineer, $150 per hour, 10 years of experience required.",
      "Earn $5,000 weekly.",
      "No experience required.",
      "Salary $450,000 per year plus bonus."],
     []),
    ("urgency",
     ["Reply within 30 minutes to secure your position.",
      "Act now! Limited spots.",
      "Urgently hiring, start today."],
     ["Applications close October 30.",
      "Reply within 3 days.",
      "We are hiring for the platform team."],
     ["There is no need to act now."]),
    ("instant_offer",
     ["No interview required. You're hired immediately.",
      "Guaranteed job for everyone who signs up.",
      "Hired on the spot."],
     ["Interview process: two rounds with the team.",
      "We will contact shortlisted candidates.",
      "Software engineer, Python."],
     ["This is not a guaranteed job; we interview every candidate."]),
    ("reshipping",
     ["Receive packages at your home and reship them.",
      "You will receive parcels at your address and forward them overseas."],
     ["Warehouse associate: pack and ship customer orders.",
      "Delivery drivers deliver packages to customers' homes.",
      "Receive packages from carriers at the loading dock."],
     []),
    ("task_deposit",
     ["Deposit money to unlock tasks.",
      "Recharge your account to continue.",
      "Commission is unlocked after deposit."],
     ["Tasks are assigned weekly by your manager."],
     ["No deposit is needed to receive tasks."]),
    ("paid_engagement",
     ["Get paid to like and rate products online.",
      "App optimization tasks, paid per task."],
     ["Quality rater: evaluate search results for accuracy.",
      "Customer reviews are collected by our support team."],
     []),
    ("personal_email",
     ["Send your resume to hiring.manager@gmail.com.",
      "Contact us at JOBS@GMAIL.COM for details.",
      "Questions? recruiter@yahoo.com"],
     ["Send your resume to careers@acme.com.",
      "Apply through our website.",
      "Email: jane@outlook.company.example"],
     []),
]


def test_each_rule():
    covered = {rule.id for rule in RULES}
    check("every rule in the table has test examples", covered == {case[0] for case in RULE_CASES})
    for rule_id, positives, controls, negated in RULE_CASES:
        for text in positives:
            found = ids(text)
            check(f"[{rule_id}] flagged: {text[:70]!r}", rule_id in found, f"found {found}")
        for text in controls:
            found = ids(text)
            check(f"[{rule_id}] NOT flagged (ordinary text): {text[:70]!r}", rule_id not in found, f"found {found}")
        for text in negated:
            found = ids(text)
            check(f"[{rule_id}] NOT flagged (negated or covered): {text[:70]!r}", rule_id not in found, f"found {found}")


def test_specific_requirements():
    """The explicit examples from the milestone brief."""
    check("'Pay a $50 application fee.' is flagged", "upfront_payment" in ids("Pay a $50 application fee."))
    check("'No application fee is required.' is NOT flagged", ids("No application fee is required.") == [])
    check("'Company provides a laptop.' is not an equipment-payment scam", ids("Company provides a laptop.") == [])
    check("check + deposit + purchase is flagged",
          "fake_check" in ids("We will send a check. Deposit it and purchase your laptop."))
    check("'Experience with PayPal APIs.' is NOT a payment-method signal", ids("Experience with PayPal APIs.") == [])
    check("'Send payment through PayPal.' is flagged", "payment_method" in ids("Send payment through PayPal."))
    check("'Competitive salary: $180,000' is NOT unrealistic pay", ids("Competitive salary: $180,000") == [])
    check("high pay + no experience + one hour daily is flagged",
          "unrealistic_pay" in ids("Earn $5,000 weekly, no experience, work one hour daily."))
    check("'Applications close October 30.' is NOT urgency", ids("Applications close October 30.") == [])
    check("'Reply within 30 minutes to secure your position.' is flagged",
          "urgency" in ids("Reply within 30 minutes to secure your position."))
    check("remote / work from home / hybrid alone is not a signal",
          ids("Remote position. Work from home with hybrid options. Responsibilities: answer customer tickets.") == [])
    check("a missing interview section is not read as 'no interview'",
          ids("Software engineer. Requirements: Python. Benefits: health insurance.") == [])
    check("no e-mail address in the text means no e-mail signal",
          "personal_email" not in ids("Apply on our website. Competitive pay."))


def test_severity_and_structure():
    suspicious = ("Work From Home - Earn $5000 Weekly!!!\n\nJob Description\nNo experience needed! Limited spots. "
                  "Send your full name and bank account details. A small registration fee is required.\n"
                  "Email jobs@gmail.com")
    result = scan_job_signals(suspicious)
    check("result has exactly the keys signals and signal_count", set(result) == {"signals", "signal_count"})
    check("signal_count equals the number of signals", result["signal_count"] == len(result["signals"]) > 0)
    expected_keys = {"id", "title", "category", "severity", "evidence", "more_evidence", "explanation",
                     "recommended_action", "details"}
    check("every signal has the documented fields", all(set(s) == expected_keys for s in result["signals"]))
    check("severity is only high, medium or notice", all(s["severity"] in SEVERITIES for s in result["signals"])
          and SEVERITIES == ("high", "medium", "notice"))
    order = [SEVERITIES.index(s["severity"]) for s in result["signals"]]
    check("signals are ordered high, then medium, then notice", order == sorted(order), str(order))
    check("every signal has a title, explanation and next step",
          all(s["title"] and s["explanation"] and s["recommended_action"] for s in result["signals"]))
    forbidden = ("score", "probability", "percent", "risk_level", "safety")
    flat_keys = set(result) | {key for s in result["signals"] for key in s}
    check("there is no second score, probability or risk level anywhere in the result",
          not any(word in key.lower() for key in flat_keys for word in forbidden), str(sorted(flat_keys)))
    severities = {rule.id: rule.severity for rule in RULES}
    check("severity table follows the brief (payment, check, sensitive info, payment method = high)",
          all(severities[i] == "high" for i in ("upfront_payment", "fake_check", "sensitive_info", "payment_method")))
    check("severity table follows the brief (personal e-mail, instant offer, reshipping, unrealistic pay = medium)",
          all(severities[i] == "medium" for i in ("personal_email", "instant_offer", "reshipping", "unrealistic_pay")))
    check("urgency is only a notice", severities["urgency"] == "notice")
    check("the scanner is deterministic", scan_job_signals(suspicious) == scan_job_signals(suspicious))
    check("extracted_fields does not change the result (reserved parameter)",
          scan_job_signals(suspicious) == scan_job_signals(suspicious, {"title": "x", "description": "y"}))
    check("blank, whitespace-only and non-text input give zero signals, not an error",
          all(scan_job_signals(value) == {"signals": [], "signal_count": 0} for value in ("", "  \n ", None, 5)))
    emails = scan_job_signals("Write to Jane at jane.doe@gmail.com or jobs@yahoo.com or hr@acme.com.")["signals"]
    check("personal e-mail signal lists the personal addresses it found, and not the company address",
          len(emails) == 1 and emails[0]["details"]["emails"] == ["jane.doe@gmail.com", "jobs@yahoo.com"],
          str(emails[0]["details"]) if emails else "none")


def test_evidence_integrity():
    """Every quote must be a real piece of the text. Nothing is invented or paraphrased."""
    long_sentence = ("We are a large and growing organization with many teams and a proud history, " * 8
                     + "and applicants must pay a registration fee before the start date " + "of the programme and so on " * 8)
    samples = [text for _, positives, _, negated in RULE_CASES for text in positives + negated]
    samples += [
        long_sentence,
        "Work From Home - Earn $5000 Weekly!!!\n\nJob Description\nNo experience needed! Limited spots.\n"
        "Send your full name and bank account details. A small registration fee is required.\n\nemail: jobs@gmail.com",
        "- Pay a $50 application fee.\n- Send your SSN to jobs@gmail.com\n* Reply immediately\r\nWe will send you a check "
        "to purchase equipment, then deposit the check.",
        "WE WILL SEND A CHECK.\tDEPOSIT IT AND PURCHASE YOUR LAPTOP.  Earn   $800   a day,   one   hour only.",
        "Registration fee required \u2014 \u201cpay now\u201d \u2022 caf\u00e9 \u2022 paypal \u2022 Send payment via PayPal.",
    ]
    problems, quotes, longest = [], 0, 0
    for text in samples:
        for signal in scan_job_signals(text)["signals"]:
            for quote in [signal["evidence"]] + signal["more_evidence"]:
                quotes += 1
                longest = max(longest, len(quote))
                if not quote or quote not in text or len(quote) > MAX_EVIDENCE_CHARS:
                    problems.append((signal["id"], quote[:60]))
            if not signal["evidence"]:
                problems.append((signal["id"], "no evidence"))
    check(f"all {quotes} quotes found in the scanned text are exact substrings of it, non-empty and short",
          not problems and quotes > 30, str(problems[:3]))
    check(f"the longest quote is {longest} characters (limit {MAX_EVIDENCE_CHARS})", longest <= MAX_EVIDENCE_CHARS)

    result = scan_job_signals(long_sentence)
    long_signal = [s for s in result["signals"] if s["id"] == "upfront_payment"]
    check("a very long sentence is shortened around the matched words, still verbatim",
          long_signal and "registration fee" in long_signal[0]["evidence"]
          and len(long_signal[0]["evidence"]) <= MAX_EVIDENCE_CHARS and long_signal[0]["evidence"] in long_sentence)
    fee = scan_job_signals("Pay a $75 registration fee to start.")["signals"][0]
    check("the evidence for a fee is the sentence the user wrote, character for character",
          fee["evidence"] == "Pay a $75 registration fee to start.")
    multi = scan_job_signals("Earn $5000 weekly!!!\n\nNo experience needed!")["signals"][0]
    check("a two-part rule (pay + little effort) quotes both parts separately, each verbatim",
          multi["evidence"] == "Earn $5000 weekly!!!" and multi["more_evidence"] == ["No experience needed!"],
          f"{multi['evidence']!r} {multi['more_evidence']}")
    messy = "Registration   fee \n\n required.\tPAY A  $50 APPLICATION  FEE now"
    check("messy spacing, tabs and capital letters still give verbatim evidence",
          all(q in messy for s in scan_job_signals(messy)["signals"] for q in [s["evidence"]] + s["more_evidence"]))


def test_independence_and_speed():
    source = Path(scam_signals.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    check("the scanner imports only the Python standard library (no model, network or AI package)",
          imported <= {"re", "bisect", "dataclasses", "typing"}, str(sorted(imported)))
    check("the scanner does not import model_service, torch, transformers or any HTTP client",
          not (imported & {"backend", "torch", "transformers", "requests", "httpx", "urllib", "openai", "anthropic"}))
    check("scanner module source never reads test.csv", "test.csv" not in source.replace("test.csv is never", ""))

    big = "We are a growing company with great culture and many benefits. " * 800     # about 50,000 characters
    hostile = ("pay " * 4000) + ("a check a check " * 1500) + ("you " * 3000)
    started = time.perf_counter()
    scan_job_signals(big)
    scan_job_signals(hostile)
    elapsed = (time.perf_counter() - started) * 1000
    check(f"two 50,000-character texts (one hostile) are scanned in {elapsed:.0f} ms (limit 3000 ms)", elapsed < 3000)


def main():
    test_each_rule()
    test_specific_requirements()
    test_severity_and_structure()
    test_evidence_integrity()
    test_independence_and_speed()
    print(f"\n{sum(results)} of {len(results)} checks passed")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
