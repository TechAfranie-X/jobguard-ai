"""JobGuard AI backend.

React frontend --JSON POST--> FastAPI --intake parser--> combined_text --> saved DistilBERT tokenizer + model
                                                                                   --> fraud probability
                                       \\--> scam signal scanner (rules; independent of the model) --> warning signs

Job URL (Milestone 14):  POST /import-url --> safe importer (backend/url_importer.py) --> posting text + verification
                         checks (backend/verification.py, facts only). The frontend then sends the text to /predict,
                         so the model still runs exactly once per analysis and is never involved in /import-url.

Run from the project root:   uvicorn backend.main:app --reload
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.intake_parser import parse_posting
from backend.model_service import MODEL_NAME, THRESHOLD, ModelService, build_combined_text
from backend.scam_signals import scan_job_signals
from backend.schemas import (DISCLAIMER, ExtractionResponse, ExtractRequest, ImportUrlRequest, ImportUrlResponse,
                             JobPostingRequest, JobPredictionResponse)
from backend.url_importer import FAILURE_MESSAGE, ImportFailure, import_job_url
from backend.verification import run_verification

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     [jobguard] %(message)s")
logger = logging.getLogger("jobguard")
# The HTTP client library logs every request URL at INFO level. Imported job URLs are private to the user, so only
# warnings and errors from it are shown.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load the tokenizer and model ONCE. If the model files are missing, this raises a clear error
    # and the server refuses to start.
    app.state.model_service = ModelService.load()
    yield
    # Shutdown: release the model
    app.state.model_service.close()
    app.state.model_service = None


app = FastAPI(
    title="JobGuard AI API",
    description="Submit a job posting and receive a fraud risk signal from the fine-tuned DistilBERT model.",
    version="1.3.0",
    lifespan=lifespan,
)

# Only the local React/Vite development server may call this API from a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def root():
    return {"name": "JobGuard AI API", "status": "running"}


@app.get("/health")
def health(request: Request):
    service = getattr(request.app.state, "model_service", None)
    return {
        "status": "ok" if service is not None else "unavailable",
        "model_loaded": service is not None,
        "model": MODEL_NAME,
        "device": service.device if service is not None else None,
    }


@app.post("/extract", response_model=ExtractionResponse)
def extract(posting: ExtractRequest):
    """Show how a pasted posting would be split into sections. Rule-based only: the model is not used here."""
    return parse_posting(posting.raw_posting).to_dict()


@app.post("/import-url", response_model=ImportUrlResponse)
def import_url(request_body: ImportUrlRequest):
    """Import a public job page and run the verification checks. The DistilBERT model is NOT used here.

    The frontend then sends the returned `raw_posting` to POST /predict, so the existing prediction code is not
    duplicated and a completed analysis makes exactly one model inference. Verification (URL, hosting, contact
    domains) is computed from the page's address and the two optional details; it never touches the text or the
    score. Nothing is stored. A page that cannot be imported is a normal answer (imported=false), not an error.
    """
    try:
        imported = import_job_url(request_body.url)
    except ImportFailure as failure:
        logger.info("URL import stopped (%s)", failure.reason)           # no URL or page content in the log
        return ImportUrlResponse(imported=False, message=FAILURE_MESSAGE, reason=failure.reason)
    except Exception:
        logger.exception("URL import failed unexpectedly")
        return ImportUrlResponse(imported=False, message=FAILURE_MESSAGE, reason="unreachable")

    started = time.perf_counter()
    verification = run_verification(
        final_url=imported["final_url"], requested_url=imported["requested_url"],
        redirect_count=imported["redirect_count"], structured_job_data_found=imported["structured_job_data_found"],
        company_website=request_body.company_website, recruiter_email=request_body.recruiter_email)
    verification_ms = round((time.perf_counter() - started) * 1000, 2)

    source_keys = ("requested_url", "final_url", "source_domain", "redirect_count", "https",
                   "structured_job_data_found", "page_title", "company_name")
    return ImportUrlResponse(
        imported=True,
        message="Page imported.",
        source={key: imported[key] for key in source_keys},
        raw_posting=imported["raw_posting"],
        extracted_fields=imported["extracted_fields"],
        checks=verification["checks"],
        timings_ms={**imported["timings_ms"], "verification": verification_ms},
    )


@app.post("/predict", response_model=JobPredictionResponse)
def predict(posting: JobPostingRequest, request: Request):
    service = getattr(request.app.state, "model_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="The model is not loaded.")

    try:
        # Pasted text is split into the five fields by the deterministic intake parser; separate fields are
        # used as sent. Either way the SAME training-format function builds the text DistilBERT receives.
        fields = parse_posting(posting.raw_posting).fields() if posting.raw_posting is not None \
            else posting.structured_fields()
        combined_text = build_combined_text(**fields)
        fraud_probability = service.predict(combined_text)
        # The warning-sign scanner is a separate, rule-based check on the same text. Its result never reaches the
        # model (combined_text above is already built) and it produces no score.
        scan = scan_job_signals(posting.raw_posting if posting.raw_posting is not None else
                                "\n\n".join(value for value in fields.values() if value), fields)
    except Exception:
        # Details go to the server terminal only; the frontend never sees a Python stack trace
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail="Prediction failed on the server. Please try again later.")

    is_fraud = fraud_probability >= THRESHOLD       # locked decision rule
    return JobPredictionResponse(
        prediction="fraudulent" if is_fraud else "legitimate",
        label="Potentially Fraudulent" if is_fraud else "Likely Legitimate",
        fraud_probability=round(fraud_probability, 4),
        fraud_percentage=round(fraud_probability * 100, 2),
        model=MODEL_NAME,
        threshold=THRESHOLD,
        disclaimer=DISCLAIMER,
        signals=scan["signals"],
        signal_count=scan["signal_count"],
    )
