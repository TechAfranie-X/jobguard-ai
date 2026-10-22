# Scam Signal Engine (Milestone 13)

A transparent, rule-based scanner that sits **beside** the DistilBERT classifier. Code: `backend/scam_signals.py`. Tests: `backend/test_scam_signals.py`.

## What it is for

| | DistilBERT risk score | Warning-sign scanner |
|---|---|---|
| Question it answers | "How much does this posting look like the fraudulent postings the model was trained on?" | "What should I look at more carefully in this text?" |
| Method | Fine-tuned neural network | Fixed regular-expression rules |
| Output | One fraud probability (threshold 0.5) | A list of warning signs, each with a quote from the posting |
| Explains the model? | No | **No.** It does not know what DistilBERT looked at |

The two parts are independent. The scanner never feeds DistilBERT, never changes its input, and never produces a second fraud percentage, a rule score, or an overall safety rating. A posting can have a high ML risk and no warning signs, or the other way round. The page shows them as two separate cards for that reason.

```
Raw Posting
   ↓
Smart Intake
   ├────────────→ Scam Signal Scanner
   ↓
combined_text
   ↓
DistilBERT
   ↓
Prediction
   ↓
Unified Result UI
```

For a pasted posting the scanner reads the pasted text itself. For an edited five-field request it reads the non-empty fields joined by blank lines. It is deterministic, calls no AI service, and imports only the Python standard library (`re`, `bisect`, `dataclasses`, `typing`; checked by a test).

## API shape

`POST /predict` keeps every existing field and adds two:

```json
{
  "signal_count": 1,
  "signals": [
    {
      "id": "upfront_payment",
      "title": "Upfront payment requested",
      "category": "money",
      "severity": "high",
      "evidence": "A small registration fee is required.",
      "more_evidence": [],
      "explanation": "Legitimate employers generally do not require applicants to pay a fee to get or start a job.",
      "recommended_action": "Do not send money. Verify the position directly with the employer ...",
      "details": {}
    }
  ]
}
```

Old clients ignore the new fields. `details` holds extra structured facts for a few rules (the personal-email rule lists the addresses it found). `scan_job_signals(raw_text, extracted_fields=None)` returns `{"signals": [...], "signal_count": n}`; the second argument is reserved and currently unused.

## The 12 rules

| Rule id | Severity | Category | Flags when the text... |
|---|---|---|---|
| `upfront_payment` | high | money | asks the applicant to pay a registration / application / processing / training / starter-kit / certification / equipment / activation fee, or to pay or send payment before starting |
| `fake_check` | high | money | mentions a check being sent together with depositing it, buying equipment with it, or sending back the balance |
| `sensitive_info` | high | personal_info | asks the applicant to send or provide an SSN, bank account, routing number, card, driver's licence, passport or ID |
| `payment_method` | high | money | tells the reader to pay or move money by gift card, crypto, Bitcoin, Cash App, Zelle, PayPal, or wire / money transfer |
| `task_deposit` | high | task_scheme | requires a deposit, recharge or top-up to unlock tasks or commission |
| `purchase_reimbursement` | medium | money | asks the applicant to buy their own equipment and promises to repay them |
| `unrealistic_pay` | medium | pay | combines a very high pay amount with wording about little effort or no experience |
| `instant_offer` | medium | hiring_process | explicitly says there is no interview or an instant / immediate offer |
| `reshipping` | medium | job_duties | describes receiving packages at home and forwarding them |
| `paid_engagement` | medium | task_scheme | offers payment for ratings, likes or reviews |
| `personal_email` | medium | contact | contains an email address on a free provider (gmail, yahoo, outlook, hotmail, icloud, protonmail and a few more) |
| `urgency` | notice | pressure | uses pressure wording such as "limited spots", "act now", "immediate start" |

Only three severities exist: `high`, `medium`, `notice`. Signals are listed high first, then medium, then notice.

**Deliberately left out:** "vague remote work". It is too subjective, and the part that matters (very high pay for little effort) is already covered by `unrealistic_pay`.

## Evidence

Evidence is never written by the rules. A rule only finds **character positions** in the user's text, and the quote is a slice of that text:

1. The slice is widened to the sentence that contains the match. Sentence ends are `.`, `!`, `?` followed by whitespace, or a newline, so `$5.50` and email addresses are not split.
2. If the sentence is longer than 180 characters, the window is trimmed on word boundaries and never cuts inside the matched words.
3. A signal shows one main quote plus up to two more (no duplicates).

A signal without a real quote is dropped, not shown with made-up text. The tests check that every quote is a literal substring of the input (whitespace-normalised) for every example.

## Negation and context

Plain keyword matching would flag "No application fee is required". The scanner avoids that locally:

- **Negation:** for a match, it looks at the preceding clause (up to 70 characters, cut at `.` `!` `?` `;` `:`, a newline, or words such as *but*, *however*, *although*, *except*) for *no, not, never, without, nor, neither, zero, cannot, nothing, n't, free of / from*. For fee and cost rules it also accepts *covered, reimbursed, waived, provided, refunded* and "we / the company pay(s)". It also reads the next 45 characters for "is not required", "waived", "free", "$0", "n/a" and similar.
- **Payment methods** only count when the sentence is an instruction to the reader (a sentence-start verb, "please", "you must", or "you will receive payments ... forward the funds"). "Integrate the PayPal API" does not match.
- **Sensitive information** needs a hand-over verb (send, provide, submit ...). Ambiguous items (bank account, card, licence, passport, ID) also need a "your" / "copy of" cue. Hiring-process timing ("after you accept the offer", "I-9", "first day") and requirement-style text ("valid driver's licence required") are not flagged.
- **Unrealistic pay** needs both parts within 300 characters: pay of at least $300/day, $1,500/week, $100/hour or $10,000/month (or "earn thousands every day/week"), and little-effort wording. A high salary alone never flags.
- **Fake check** needs a check noun plus a deposit-it, buy-equipment or send-the-balance instruction within 300 characters. A company laptop or ordinary expense policy is not flagged.
- **Reshipping** needs strong reshipping phrases, or receiving packages at home plus a forward / ship verb within 200 characters. Normal warehouse and logistics jobs are not flagged.
- **Instant offer** needs explicit wording. A missing interview section is never read as "no interview".
- **Urgency** is notice-level, and "applications close Friday" alone is not flagged.
- **Personal email** only appears when an address is present, and the scanner does not guess the company's correct domain.

## Language rules

Signals say "Warning sign found", "Worth verifying" and "Potential risk indicator". They never say a posting is fake, a scam, or an identity-theft attempt. A zero-signal result says:

> No common scam signals were detected in the text. This does not guarantee the posting is legitimate. JobGuard's ML risk assessment and independent verification still matter.

## Limitations

- These are fixed English text rules. They do not understand meaning, so a rule can fire on harmless wording and miss a scam phrased in a way nobody anticipated.
- Known borderline case: "Immediate start available for the right candidate." produces a notice-level urgency signal, because "immediate start" is on the pressure list.
- Negation is local (one clause). Unusual sentence structures can defeat it.
- Finding no signals does **not** mean a posting is safe. Finding signals does not prove it is fake.
- The scanner does not explain why DistilBERT gave its score.
- The scanner only reads the text. It does not check the employer, the recruiter, the email domain, or any link. Independent verification is still necessary.

## Safety guidance source

The "What should I do next?" advice is informed by public FTC job-scam guidance: [Job scams](https://consumer.ftc.gov/articles/job-scams) and [How to spot and avoid task scams](https://consumer.ftc.gov/consumer-alerts/2025/08/how-spot-avoid-task-scams). JobGuard is an independent student project and is not affiliated with or endorsed by the FTC.

## Tests

`python -m backend.test_scam_signals` runs a positive, a control (legitimate look-alike) and a negated example for every rule, the specific cases from the milestone brief, severity and structure checks, evidence-integrity checks, an import-independence check and a speed check on two ~50,000-character texts. `python -m backend.test_api` additionally runs eight real scenarios through the API and confirms that each request makes exactly one DistilBERT prediction and that turning the scanner off does not change the prediction.
