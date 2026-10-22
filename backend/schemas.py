"""Request and response shapes of the JobGuard API (Pydantic validates them automatically)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

# A generous limit per text field (real postings are far shorter). It only protects the server from huge
# accidental payloads. Text is NOT cut here: the tokenizer truncates to 256 tokens later.
MAX_FIELD_CHARS = 50_000

# Surrounding whitespace is trimmed. Nothing else is cleaned (no lowercasing, no punctuation removal).
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_FIELD_CHARS)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_FIELD_CHARS)]

DISCLAIMER = ("JobGuard provides an ML-based risk signal and is not definitive proof that a posting is "
              "legitimate or fraudulent.")

STRUCTURED_FIELDS = ("title", "company_profile", "description", "requirements", "benefits")


class JobPostingRequest(BaseModel):
    """A job posting to analyze. Send EITHER one of these two forms (not both):

    A. raw_posting: the whole pasted posting as one string. The server splits it into sections itself
       (deterministic parser, no AI service).
    B. The separate fields title / company_profile / description / requirements / benefits (the original
       form). Any field may be empty, but the posting must contain some text.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"raw_posting": "Customer Support Representative\n\nAbout Us\nExample Co. provides billing software.\n\n"
                        "Job Description\nAnswer customer questions by email and chat.\n\n"
                        "Requirements\nGood written English.\n\nBenefits\nPaid vacation."},
        {"title": "Customer Support Representative",
         "company_profile": "Example Co. provides billing software to small businesses.",
         "description": "Answer customer questions by email and chat, and help them use our software.",
         "requirements": "Good written English. One year of customer service experience.",
         "benefits": "Paid vacation and health insurance."},
    ]})

    raw_posting: OptionalText | None = None
    title: OptionalText | None = None
    company_profile: OptionalText | None = None
    description: OptionalText | None = None
    requirements: OptionalText | None = None
    benefits: OptionalText | None = None

    @model_validator(mode="after")
    def check_one_input_style(self):
        structured = [getattr(self, name) for name in STRUCTURED_FIELDS]
        if self.raw_posting is not None:
            if any(value is not None for value in structured):
                raise ValueError("Send either raw_posting or the separate fields, not both.")
            if not self.raw_posting:
                raise ValueError("raw_posting must contain some text.")
        elif not any(structured):
            raise ValueError("The posting has no text. Send raw_posting, or at least one of the separate fields.")
        return self

    def structured_fields(self):
        """The five fields of form B; a field that was not sent (or null) is an empty string, as in training."""
        return {name: getattr(self, name) or "" for name in STRUCTURED_FIELDS}


class ExtractRequest(BaseModel):
    """The pasted posting to split into sections (no prediction is made)."""

    raw_posting: RequiredText


class ExtractionResponse(BaseModel):
    """What the intake parser found. An empty string means 'not found'; nothing is guessed."""

    title: str
    company_profile: str
    description: str
    requirements: str
    benefits: str
    detected_sections: list[str]        # fields that contain text
    missing_sections: list[str]         # fields that are empty
    fallback_used: bool                 # text that was not in a recognized section was kept in description


class WarningSignal(BaseModel):
    """One warning sign found by the rule-based scanner (backend/scam_signals.py).

    This is NOT an explanation of the DistilBERT score. The scanner is independent of the model: it only points at
    words that are literally in the posting. `evidence` and `more_evidence` are exact excerpts of the submitted text.
    """

    id: str
    title: str
    category: str
    severity: Literal["high", "medium", "notice"]
    evidence: str
    more_evidence: list[str] = []
    explanation: str
    recommended_action: str
    details: dict[str, list[str]] = {}


class JobPredictionResponse(BaseModel):
    """Two independent results for one posting: the model's risk signal, and the scanner's warning signs."""

    prediction: Literal["fraudulent", "legitimate"]                    # raw machine label
    label: Literal["Potentially Fraudulent", "Likely Legitimate"]      # user-facing label
    fraud_probability: float                                           # model score for class 1 (not a calibrated certainty)
    fraud_percentage: float
    model: str
    threshold: float
    disclaimer: str
    # Rule-based warning signs (independent of the model; there is deliberately no second score)
    signals: list[WarningSignal] = []
    signal_count: int = 0


# ---------------------------------------------------------------------------------------------------------------
# Milestone 14: job URL import and verification checks
# ---------------------------------------------------------------------------------------------------------------
class ImportUrlRequest(BaseModel):
    """A public job page to import, plus two optional details to compare it with. Nothing here is stored."""

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"url": "https://company.com/careers/software-engineer", "company_website": "https://company.com",
         "recruiter_email": "recruiter@company.com"},
    ]})

    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
    company_website: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)] | None = None
    recruiter_email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None

    @field_validator("company_website", "recruiter_email")
    @classmethod
    def blank_means_not_given(cls, value):
        return value or None


class ImportSource(BaseModel):
    """Where the imported page came from. Only public information about the page; no network internals."""

    requested_url: str
    final_url: str
    source_domain: str
    redirect_count: int
    https: bool
    structured_job_data_found: bool
    page_title: str | None = None
    company_name: str | None = None          # only when the page's own JobPosting data names the employer


class VerificationCheck(BaseModel):
    """One verification fact. Facts, not verdicts: there is no score and no 'safe' or 'unsafe' status."""

    id: str
    status: Literal["confirmed", "attention", "info", "not_checked"]
    title: str
    detail: str
    result: str | None = None                # machine-readable outcome, e.g. MATCH, DIFFERENT_DOMAIN, KNOWN_ATS


class ImportUrlResponse(BaseModel):
    """The result of importing a job page. The model is NOT run here: the frontend sends `raw_posting` to
    POST /predict, so there is exactly one DistilBERT inference per analysis."""

    imported: bool
    message: str
    reason: str | None = None                # coarse failure category when imported is false
    source: ImportSource | None = None
    raw_posting: str | None = None
    extracted_fields: ExtractionResponse | None = None
    checks: list[VerificationCheck] = []
    timings_ms: dict[str, float] = {}
