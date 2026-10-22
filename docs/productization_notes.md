# Productization notes (Milestone 12)

The model did not change in this milestone. What changed is how a person uses it.

## 1. The original UX: five dataset fields

Through Milestone 11 the web page was a form with five boxes: **Job Title**, **Company Profile**, **Description**, **Requirements** and **Benefits**. Those are exactly the five text columns of the EMSCAD dataset, and they are exactly what the model was trained on (joined into `combined_text` as `TITLE: ... COMPANY PROFILE: ... DESCRIPTION: ... REQUIREMENTS: ... BENEFITS: ...`).

## 2. The problem

The form was shaped like the *dataset*, not like the *user's situation*.

- A job seeker looking at a suspicious posting has **one block of text** (a web page, an email, a message). They do not have it pre-split into five parts.
- To use the form they had to read the posting, decide which sentence belongs in which box, and copy five times. Many people would simply give up, or put everything in "Description".
- Different boxes mean different things in the training data. Putting text in the wrong box quietly gives the model input that looks different from what it learned on.
- The first screen looked like a data-entry tool, not like something that helps you check a job.

## 3. The new paste-first UX

The default flow is now **paste -> analyze -> result**:

1. One large box: "Paste job posting".
2. **Analyze Job**.
3. The result: label, fraud-risk percentage, and a short "what to do next" list.

Supporting changes:

- "Try an example" chips fill the box (they never submit by themselves).
- A small **Detected details** summary shows what was found (for example "Job title", "Requirements", "Benefits not found"). **Review extracted details** is optional and opens the five fields, editable. Most users never need it.
- The page no longer leads with metrics, dataset information, backend status or machine-learning terminology. Those moved lower down ("How JobGuard works", "Model performance", "About the project"). "Powered by DistilBERT" stays, but small.
- If the backend cannot be reached the user sees one plain sentence ("We couldn't analyze this posting right now. Please try again.").

## 4. The engineering solution: a deterministic extraction layer

A small parser, `backend/intake_parser.py`, sits **in front of** the existing pipeline and turns the pasted text into the same five fields:

```
Paste full job posting
   -> smart intake parser (rules)
   -> title / company_profile / description / requirements / benefits
   -> existing combined_text preprocessing (src/preprocessing.create_combined_text)
   -> DistilBERT (threshold 0.5, max_length 256)
   -> result
```

Design rules:

- **Deterministic and rule-based.** It recognises known headings on their own line ("About Us", "About the Role", "Qualifications", "What We Offer", "Benefits", ...). The same input always gives the same output. It uses **no generative AI and calls no external API** (no OpenAI, Claude, Gemini or similar).
- **Never invents information.** If it cannot confidently identify a section, that field is left empty.
- **Never loses text.** Anything that does not belong to a recognised section goes into `description`, once. A posting with no headings at all still reaches the model in full. Nothing is copied into several fields.
- **Headings with no matching field** (for example "Responsibilities", "Salary", "How to apply") keep their heading and are appended to `description` or `benefits`.
- **Separate from the model.** The parser decides only *where text goes*. It never looks at the prediction, and the model is never asked to parse.
- **Same training/inference format.** After extraction the backend calls the same `create_combined_text` function used to build the training data.

API compatibility: `POST /predict` accepts either `{"raw_posting": "..."}` or the original five fields (never both in one request). The response format is unchanged. A new `POST /extract` runs only the parser, so the page can show the detected summary without running the model.

One deliberate loosening: the five-field request used to require a title and a description. Because the parser never makes up a title, an edited-field request must be allowed to have an empty title, so the rule is now "at least one field must contain text".

## 5. How it was checked

- `python -m backend.test_intake_parser`: 39 checks covering labeled sections, alternate headings, no headings, missing benefits, missing company, very short text, a compensation section, and headings inside normal sentences. For every sample it checks that no word appears that the user did not paste, that no word is duplicated, and that the output is the same on repeated runs.
- `python -m backend.test_api`: 59 checks, including that the old five-field request still works, that a pasted posting reaches the model with exactly the same text the parser would build, and that one request makes exactly one model prediction.
- Browser checks of the real page: a professional posting is "Likely Legitimate"; a suspicious one is "Potentially Fraudulent"; editing a detected field changes what is analyzed; blank input is refused politely; a stopped backend shows the friendly message; Clear resets; the layout has no horizontal scrolling at 320, 390 and 768 px.

## 6. Why it matters

The model is the same model, with the same weights, the same 0.5 threshold, the same 256-token limit and the same input format. It still has the same strengths and limits (see `docs/presentation_facts.md`). What improved is usability: a person can now check a posting in one paste instead of filling in five boxes, which is a much more realistic way to use a fraud detector. The project's accuracy numbers were not re-measured and did not change; no new evaluation was run.

## 7. Known limits of the intake parser

- It only knows headings that are in its list. A posting that uses unusual headings is not split up; its text goes to `description`, which is safe (the model still reads everything) but gives a less tidy "Detected details" summary.
- A heading must be on its own line. A heading phrase inside a normal sentence is not treated as a heading (this is tested on purpose).
- It only handles English-language headings.
- It is designed for job postings. Recruiter messages and offer letters are not formally supported.
- The model reads only the first 256 tokens of the combined text, so very long postings are still truncated (an existing, documented limit).
