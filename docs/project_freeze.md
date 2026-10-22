# Project Freeze

**Freeze date:** 2026-10-21 (end of Milestone 11)

**No model tuning should occur after this freeze.**

The model, the decision threshold, the preprocessing and the product feature set are locked.
From this point the project can only be presented and documented, not improved.

---

## What is frozen

| Item | Frozen value |
|---|---|
| Final model | Fine-tuned `distilbert-base-uncased` (baseline, no class weights), saved in `models/distilbert/` |
| Decision threshold | **0.5** (fraudulent if fraud probability >= 0.5) |
| `max_length` | **256** tokens (truncation on) |
| Preprocessing | `combined_text` = TITLE / COMPANY PROFILE / DESCRIPTION / REQUIREMENTS / BENEFITS |
| Training | 2 epochs, learning rate 2e-5, batch size 16, weight decay 0.01, seed 42, Colab Tesla T4, 12,852 training rows |
| Frontend features | Paste box, two examples, analyze, result card with disclaimer, clear/reset, About section (see the Milestone 12 addendum below for the intake changes) |

## Final test metrics (four models, `test.csv`, 3,214 postings, 144 fraudulent)

Source: `results/metrics/final_test_model_comparison.csv`

| Model | Accuracy | Fraud Precision | Fraud Recall | Fraud F1 |
|---|---|---|---|---|
| Logistic Regression | 0.9692 | 0.6178 | 0.8194 | 0.7045 |
| Multinomial Naive Bayes | 0.9776 | 0.8273 | 0.6319 | 0.7165 |
| XGBoost | 0.9795 | 0.8250 | 0.6875 | 0.7500 |
| **DistilBERT (selected)** | **0.9841** | **0.8843** | **0.7431** | **0.8075** |

DistilBERT confusion matrix: 3,056 true negatives, 14 false positives, 37 false negatives, 107 true positives.

## Checks at freeze time

| Check | Result |
|---|---|
| `python -m backend.test_api` | **39 of 39 checks passed** |
| `npm run lint` (frontend) | Passed, exit code 0 |
| `npm run build` (frontend) | Passed, exit code 0 |
| Demo examples verified through the real UI and API | Professional: Likely Legitimate, probability 0.0007 (0.07%). Suspicious: Potentially Fraudulent, probability 0.9891 (98.91%). |
| Required-field, optional-field, backend-offline-and-recovery, and reset tests | Passed in the live app |
| Responsive layout | Checked at 1280, 768, 390 and 320 px wide |
| Keyboard focus | Visible on all controls (checked with browser focus emulation, not a physical keyboard) |

## Fingerprints (MD5)

Re-checked at freeze. They match the values recorded when the models were locked (`results/metrics/final_model_lock.csv`).

| File | MD5 |
|---|---|
| `models/logistic_regression_pipeline.joblib` | `9b65387b1cc247449cbe1180947e9ce0` |
| `models/naive_bayes_pipeline.joblib` | `d6c7fe75988d0b1e2592288b2a82d1ee` |
| `models/xgboost_pipeline.joblib` | `d6da463fa15e4b4b3a6f407f8ffd319d` |
| `models/distilbert/` (MD5 of the four files' MD5s: `config.json`, `model.safetensors`, `tokenizer.json`, `tokenizer_config.json`) | `abda59d6056ecfa66909497e7291f5f0` |
| `data/processed/train.csv` | `0a5b5a32b8d08433aa9858ac2ec5eb71` |
| `data/processed/test.csv` | `980610d447225de4f8ef37c819b2fc45` |

The raw data file `data/raw/fake_job_postings.csv` has never been modified (its file date is from the original download).

## What is allowed after the freeze

- Creating the presentation.
- Fixing wording and documentation.
- Visual polish that does **not** change predictions.
- Demo rehearsal.

## What is NOT allowed after the freeze

- Retraining or fine-tuning any model.
- Changing the 0.5 threshold or `max_length`.
- Changing the text preprocessing.
- Using `test.csv` to make any new decision.
- Adding features, authentication, a database or a cloud deployment.

If a problem is found in the app, report it as a limitation instead of changing the model.

## Known limitations (carried into the presentation)

See `docs/presentation_facts.md`, section LIMITATIONS. In short: one dataset, 144 test fraud cases, 37 scams missed, long postings truncated to 256 tokens, the percentage is a risk signal and not proof, and Logistic Regression was inspected on the test set once, early on (methodology caveat).

## Milestone 12 addendum (productization, 2026-10-21)

Milestone 12 changed how a user gives the posting to the model, not the model. Everything in the "What is frozen" table above is unchanged **except the frontend feature set**, which was deliberately redesigned: the five-field form became a single paste box, a deterministic rule-based parser (`backend/intake_parser.py`, no generative AI, no external API) splits the pasted text into the same five fields, the result card gained a short next-steps list, and the backend status pill was removed.

- Unchanged: model weights, 0.5 threshold, `max_length` 256, the TITLE / COMPANY PROFILE / DESCRIPTION / REQUIREMENTS / BENEFITS format (still built by the same `create_combined_text`), all final test metrics, the raw data. No training was run and `test.csv` was not used.
- API: `POST /predict` still accepts the five fields and now also `raw_posting`; the response is unchanged. The five-field request now needs only some text in at least one field (it used to require a title and a description) because the parser never invents a title. `POST /extract` was added (parser only, no model).
- Checks after Milestone 12: `python -m backend.test_api` 59 of 59 passed, `python -m backend.test_intake_parser` 39 of 39 passed, `npm run lint` and `npm run build` exit 0. All six file fingerprints in the table above were re-checked and are unchanged. (The "39 of 39" in the table above is the Milestone 11 API test count.)
- Details: `docs/productization_notes.md`.

## Milestone 13 addendum (warning-sign scanner)

Milestone 13 added a second, independent output next to the model's score. It did not touch the model. A deterministic rule engine (`backend/scam_signals.py`, standard library only, no generative AI, no external API) quotes concrete warning signs found in the pasted text. It never feeds DistilBERT and does not explain its score.

- Unchanged: model weights, 0.5 threshold, `max_length` 256, tokenization, the TITLE / COMPANY PROFILE / DESCRIPTION / REQUIREMENTS / BENEFITS format, all final test metrics, the raw data. No training was run and `test.csv` was not used.
- API: `POST /predict` keeps every earlier field and adds `signals` and `signal_count`. The version is now 1.2.0.
- Frontend: the result is now an ML-risk card plus a separate Warning signs card, a next-steps panel, a "How this result works" note and an FTC guidance note.
- Checks after Milestone 13: `python -m backend.test_api` 95 of 95, `python -m backend.test_intake_parser` 39 of 39, `python -m backend.test_scam_signals` 125 of 125, `npm run lint` and `npm run build` exit 0. All six file fingerprints in the table above were re-checked and are unchanged.
- Details: `docs/scam_signal_engine.md`.

## Milestone 14 addendum (job URL import and verification)

Milestone 14 added a third, independent layer and a second way to give JobGuard a job. It did not touch the model. A safe fetcher (`backend/url_importer.py`) reads one public job page and hands its text to the existing Smart Intake Parser; a deterministic verification module (`backend/verification.py`, no generative AI, no external API) reports facts about the link and the optional company website and recruiter email. Verification has no score or verdict, never feeds DistilBERT, and does not change the warning signs.

- Unchanged: model weights, 0.5 threshold, `max_length` 256, tokenization, the TITLE / COMPANY PROFILE / DESCRIPTION / REQUIREMENTS / BENEFITS format, the intake parser, the scam scanner, all final test metrics, the raw data. No training was run and `test.csv` was not used (the new code does not read any dataset file).
- API: new `POST /import-url` (fetch, extract, verify; no model). `/predict`, `/extract` and `/health` are unchanged. The frontend sends the imported text to `/predict`, so there is exactly one model inference per analysis. The version is now 1.3.0.
- Frontend: two input modes (Paste Job Posting, the default and unchanged, and Job URL), optional verification details, a Verification card, a "What this means" note and a Switch to Paste fallback.
- Dependencies added: `beautifulsoup4` and `tldextract` (bundled public-suffix snapshot only; nothing is downloaded while serving a request). No browser-automation package.
- Privacy: JobGuard does not currently store analyses. There is no database; the URL, company website and recruiter email are not saved or logged.
- Checks after Milestone 14: `python -m backend.test_intake_parser` 39 of 39, `python -m backend.test_scam_signals` 125 of 125, `python -m backend.test_url_importer` 144 of 144, `python -m backend.test_verification` 137 of 137, `python -m backend.test_api` 137 of 137, `npm run lint` and `npm run build` exit 0. All six file fingerprints in the table above were re-checked and are unchanged.
- Details: `docs/job_verification.md`.
