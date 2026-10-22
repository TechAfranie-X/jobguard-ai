"""Tests for the smart intake parser (backend/intake_parser.py).

Run from the project root:   python -m backend.test_intake_parser

Only hand-written demonstration text is used. No model is loaded, and test.csv is never read.
Besides checking the extracted fields, every sample is run through two safety checks:
  * nothing is lost:      every word of the pasted text is in one of the five fields, except the words of
                          section headings that the parser removed on purpose (e.g. the word "Requirements")
  * nothing is invented:  the fields contain no word that was not in the pasted text, and no word is copied
                          into two places
"""

import re
import sys
from collections import Counter

from backend.intake_parser import (FIELD_NAMES, HEADING_KINDS, _HEADINGS, _KEEP_HEADING, _match_heading,
                                   parse_posting)

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))


def words(text):
    return Counter(re.findall(r"\w+", text.lower()))


def removed_heading_words(raw):
    """The words the parser is ALLOWED to drop: headings that name a field (the model input adds its own label)."""
    dropped = Counter()
    for line in raw.replace("\r\n", "\n").split("\n"):
        match = _match_heading(line)
        if match and match[0] not in _KEEP_HEADING:
            dropped += words(line) - words(match[1])
    return dropped


def text_is_preserved_and_not_invented(raw):
    fields = parse_posting(raw).fields()
    output = Counter()
    for value in fields.values():
        output += words(value)
    raw_words = words(raw)
    lost = raw_words - output
    invented_or_copied = output - raw_words
    return lost == removed_heading_words(raw) and not invented_or_copied


# ---- sample postings (hand-written, not real jobs) ----
LABELED = """Senior Data Analyst

About Us
Northwind Analytics is a data company serving hospitals and universities.

Job Description
We are looking for an analyst to join our reporting team.

Requirements
3 years of SQL. Experience with dashboards.

Benefits
Health insurance and paid vacation."""

ALTERNATE = """Customer Support Specialist

Who We Are
Bluebird Software makes billing tools for small shops.

About the Role
You will help customers by email and chat.

What You'll Do
- Answer questions
- Report bugs to the product team

Qualifications
- Clear written English
- One year in a support job

What We Offer
Paid vacation and a learning budget."""

NO_HEADINGS = ("We are hiring people to work from home. No experience needed. Earn thousands every week. "
               "Send your name and address to start today.")

NO_BENEFITS = """Warehouse Associate

About the Company
Harbor Logistics moves goods between ports and stores.

Job Description
Load and unload trucks and keep the warehouse tidy.

Requirements
Able to lift 20 kg. Forklift license preferred."""

NO_COMPANY = """Nurse Assistant

Job Description
Support nurses with daily patient care.

Requirements
Nursing assistant certificate.

Benefits
Health insurance."""

VERY_SHORT = "Data Entry Clerk\nWork from home. Apply now."

WITH_COMPENSATION = """Delivery Driver

Job Description
Deliver parcels in the city.

Requirements
Driving license.

Salary
$18 to $22 per hour, paid weekly.

Benefits
Fuel card and uniform."""

SENTENCE_HEADINGS = ("Great opportunity. We offer great benefits and the requirements are flexible. "
                     "Our qualifications matter less than attitude, and the description of the role is simple. "
                     "About us: we are a small team.")

MARKDOWN = """## Product Designer

**About Us**
A design studio.

## Requirements:
Portfolio of work.

**Benefits:** Remote work, flexible hours."""

INLINE = """Job Title: Backend Developer
About the Company: Acme builds payment software.
Requirements: Python, SQL, APIs
Benefits: Equity and health insurance"""

MESSY = """Office Assistant
Pay: $15 per hour
Location: Remote
Answer phones and file documents.
How to apply
Send a short message to the hiring team."""

ALL_SAMPLES = {"labeled": LABELED, "alternate headings": ALTERNATE, "no headings": NO_HEADINGS,
               "missing benefits": NO_BENEFITS, "missing company": NO_COMPANY, "very short": VERY_SHORT,
               "compensation section": WITH_COMPENSATION, "headings inside sentences": SENTENCE_HEADINGS,
               "markdown headings": MARKDOWN, "inline headings": INLINE, "messy posting": MESSY}


def main():
    # 1. Clearly labeled sections
    r = parse_posting(LABELED)
    check("1. labeled posting: all five fields found",
          r.title == "Senior Data Analyst" and r.company_profile.startswith("Northwind Analytics")
          and r.description == "We are looking for an analyst to join our reporting team."
          and r.requirements == "3 years of SQL. Experience with dashboards."
          and r.benefits == "Health insurance and paid vacation." and r.missing_sections == [])
    check("1. headings that name a field are removed from the text", "Requirements" not in r.requirements
          and "Benefits" not in r.benefits and "About Us" not in r.company_profile)

    # 2. Alternate headings
    r = parse_posting(ALTERNATE)
    check("2. alternate headings are recognized (Who We Are / About the Role / Qualifications / What We Offer)",
          r.company_profile.startswith("Bluebird Software") and r.requirements.startswith("- Clear written English")
          and r.benefits == "Paid vacation and a learning budget." and r.title == "Customer Support Specialist")
    check("2. 'What You'll Do' stays inside the description with its own heading",
          r.description.startswith("You will help customers") and "What You'll Do\n- Answer questions" in r.description)

    # 3. No headings: nothing is lost, everything is kept in the description
    r = parse_posting(NO_HEADINGS)
    check("3. no headings: the whole text is kept in DESCRIPTION",
          r.description == NO_HEADINGS and r.title == r.company_profile == r.requirements == r.benefits == "")
    check("3. no headings: other fields are reported missing and the fallback is flagged",
          r.missing_sections == ["title", "company_profile", "requirements", "benefits"] and r.fallback_used)

    # 4. Missing benefits
    r = parse_posting(NO_BENEFITS)
    check("4. missing benefits: left empty and reported", r.benefits == "" and "benefits" in r.missing_sections
          and r.requirements.startswith("Able to lift") and r.company_profile.startswith("Harbor Logistics"))

    # 5. Missing company information
    r = parse_posting(NO_COMPANY)
    check("5. missing company information: left empty and reported",
          r.company_profile == "" and "company_profile" in r.missing_sections and r.benefits == "Health insurance.")

    # 6. Very short posting
    r = parse_posting(VERY_SHORT)
    check("6. very short posting: title taken from the first line, rest kept",
          r.title == "Data Entry Clerk" and r.description == "Work from home. Apply now.")
    r = parse_posting("Work from home")
    check("6. a single line is not turned into a title, it is kept as DESCRIPTION",
          r.title == "" and r.description == "Work from home")
    r = parse_posting("   \n \n")
    check("6. blank text gives an empty result (the API rejects blank input before parsing)",
          all(getattr(r, name) == "" for name in FIELD_NAMES))

    # 7. Compensation section
    r = parse_posting(WITH_COMPENSATION)
    check("7. a Salary section goes to BENEFITS and keeps its heading line",
          r.benefits == "Salary\n$18 to $22 per hour, paid weekly.\n\nFuel card and uniform."
          or r.benefits == "Fuel card and uniform.\n\nSalary\n$18 to $22 per hour, paid weekly.", repr(r.benefits))
    check("7. the Salary text is not duplicated anywhere else",
          sum(value.count("$18") for value in r.fields().values()) == 1)
    r = parse_posting("Cook\nCompensation: $20 per hour\nRequirements\nCooking experience")
    check("7. inline 'Compensation: ...' is kept as written in BENEFITS", r.benefits == "Compensation: $20 per hour")

    # 8. Headings inside normal sentences are not headings
    r = parse_posting(SENTENCE_HEADINGS)
    check("8. heading words inside sentences do not split the text",
          r.description == SENTENCE_HEADINGS and r.requirements == r.benefits == r.company_profile == "")
    check("8. a bullet that starts with a heading word is not a heading",
          _match_heading("- Requirements: must be 18") is None and _match_heading("1. Benefits") is None)
    check("8. a lowercase word on its own line is not a heading, but 'Benefits' with a capital is",
          _match_heading("benefits") is None and _match_heading("Benefits") == ("benefits", ""))
    check("8. a sentence that begins with a heading word is not a heading",
          _match_heading("Benefits include health insurance.") is None and _match_heading("Benefits.") is None)
    check("8. text before the colon must be exactly a heading ('Our requirements: x' is not)",
          _match_heading("Our requirements: x") is None and _match_heading("Requirements: x") == ("requirements", "x"))

    # More formats seen in real postings
    r = parse_posting(MARKDOWN)
    check("markdown headings (##, **) and '**Benefits:** text' are understood",
          r.title == "Product Designer" and r.company_profile == "A design studio."
          and r.requirements == "Portfolio of work." and r.benefits == "Remote work, flexible hours.", str(r.fields()))
    r = parse_posting(INLINE)
    check("inline 'Heading: text' form is understood",
          r.title == "Backend Developer" and r.company_profile == "Acme builds payment software."
          and r.requirements == "Python, SQL, APIs" and r.benefits == "Equity and health insurance"
          and r.description == "")
    r = parse_posting(MESSY)
    check("unplaced text (Location, How to apply) is kept in DESCRIPTION, pay in BENEFITS",
          r.title == "Office Assistant" and r.benefits == "Pay: $15 per hour"
          and r.description == "Location: Remote\nAnswer phones and file documents.\n\nHow to apply\n"
                               "Send a short message to the hiring team.",
          repr(r.description))
    r = parse_posting("Analyst\r\n\r\nRequirements\r\nExcel\r\n")
    check("Windows line endings (CRLF) are handled", r.title == "Analyst" and r.requirements == "Excel")
    check("the title is not taken from a long sentence",
          parse_posting("Acme Corporation is looking for a motivated person to join our growing team in the city.\n"
                        "Requirements\nNone").title == "")

    # Safety properties, checked on every sample
    for name, raw in ALL_SAMPLES.items():
        check(f"no text lost, none invented, none copied twice: {name}", text_is_preserved_and_not_invented(raw))
    check("fields are never all empty for a non-blank posting",
          all(any(parse_posting(raw).fields().values()) for raw in ALL_SAMPLES.values()))

    # Determinism
    check("same input gives exactly the same output (deterministic)",
          all(parse_posting(raw).to_dict() == parse_posting(raw).to_dict() for raw in ALL_SAMPLES.values()))
    check("every known heading belongs to exactly one kind",
          len(HEADING_KINDS) == sum(len(aliases) for aliases in _HEADINGS.values()))

    # Report fields
    r = parse_posting(LABELED)
    check("detected_sections and missing_sections together list each field exactly once",
          sorted(r.detected_sections + r.missing_sections) == sorted(FIELD_NAMES))

    print(f"\n{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
