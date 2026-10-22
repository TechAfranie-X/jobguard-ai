// All communication with the FastAPI backend lives in this file.
// The frontend never decides if a posting is fraudulent - it only shows what the backend returns.

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const REQUEST_TIMEOUT_MS = 30000;

// Every failure the user can see uses plain product language, never server or technical terms.
export const GENERIC_MESSAGE = "We couldn't analyze this posting right now. Please try again.";
export const EMPTY_MESSAGE = "Please paste a job posting to analyze.";
const TOO_LONG_MESSAGE = "This posting is too long. Please shorten it and try again.";

// An error whose message is always safe to show to the user.
export class ApiError extends Error {
  constructor(message, kind) {
    super(message);
    this.name = "ApiError";
    this.kind = kind; // "network" | "validation" | "server" | "malformed"
  }
}

// fetch() wrapper that adds a timeout and turns browser network failures into a clean error.
async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(`${API_URL}${path}`, { ...options, signal: controller.signal });
  } catch {
    throw new ApiError(GENERIC_MESSAGE, "network");
  } finally {
    clearTimeout(timer);
  }
}

// Reads the body as JSON; returns null when the body is not valid JSON.
async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

// Turn a FastAPI 422 response into one friendly sentence (never the raw JSON).
function validationMessage(body) {
  const details = Array.isArray(body?.detail) ? body.detail : [];
  const tooLong = details.some((d) => String(d?.type || "").includes("too_long"));
  return tooLong ? TOO_LONG_MESSAGE : EMPTY_MESSAGE;
}

function postJson(path, payload) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

const SEVERITIES = ["high", "medium", "notice"];

// A warning sign from the rule-based scanner. Evidence must be real text, never empty.
function isValidSignal(signal) {
  return (
    signal &&
    typeof signal.id === "string" &&
    typeof signal.title === "string" &&
    SEVERITIES.includes(signal.severity) &&
    typeof signal.evidence === "string" &&
    signal.evidence.length > 0 &&
    Array.isArray(signal.more_evidence) &&
    signal.more_evidence.every((quote) => typeof quote === "string") &&
    typeof signal.explanation === "string" &&
    typeof signal.recommended_action === "string"
  );
}

// Check that the prediction has the shape we expect before showing it.
// `signals` is optional so an older backend that does not send warning signs still works (the page then
// simply shows no warning-sign section).
function isValidPrediction(data) {
  return (
    data &&
    (data.prediction === "fraudulent" || data.prediction === "legitimate") &&
    typeof data.label === "string" &&
    typeof data.fraud_percentage === "number" &&
    Number.isFinite(data.fraud_percentage) &&
    data.fraud_percentage >= 0 &&
    data.fraud_percentage <= 100 &&
    typeof data.model === "string" &&
    typeof data.disclaimer === "string" &&
    (data.signals === undefined ||
      (Array.isArray(data.signals) && data.signals.every(isValidSignal) && data.signal_count === data.signals.length))
  );
}

const SECTION_FIELDS = ["title", "company_profile", "description", "requirements", "benefits"];

function isValidExtraction(data) {
  return (
    data &&
    SECTION_FIELDS.every((name) => typeof data[name] === "string") &&
    Array.isArray(data.detected_sections) &&
    Array.isArray(data.missing_sections)
  );
}

// POST /predict -> the backend's prediction object.
// `posting` is either { raw_posting } (the pasted text) or the five separate fields (after the user edited them).
export async function analyzePosting(posting) {
  const response = await postJson("/predict", posting);
  const body = await readJson(response);

  if (response.status === 422) throw new ApiError(validationMessage(body), "validation");
  if (!response.ok) throw new ApiError(GENERIC_MESSAGE, "server");
  if (!isValidPrediction(body)) throw new ApiError(GENERIC_MESSAGE, "malformed");
  return body;
}

export const EMPTY_URL_MESSAGE = "Please enter a job posting URL to analyze.";
const BAD_URL_MESSAGE = "Please enter a valid job posting URL.";

// Verification checks report facts, so the statuses carry no verdict.
const CHECK_STATUSES = ["confirmed", "attention", "info", "not_checked"];

function isValidCheck(check) {
  return (
    check &&
    typeof check.id === "string" &&
    CHECK_STATUSES.includes(check.status) &&
    typeof check.title === "string" &&
    check.title.length > 0 &&
    typeof check.detail === "string"
  );
}

function isValidSource(source) {
  return (
    source &&
    typeof source.source_domain === "string" &&
    source.source_domain.length > 0 &&
    typeof source.requested_url === "string" &&
    typeof source.final_url === "string" &&
    Number.isInteger(source.redirect_count) &&
    typeof source.https === "boolean" &&
    typeof source.structured_job_data_found === "boolean"
  );
}

// A failed import is a normal answer (imported: false). A successful one must carry the page text and its source.
function isValidImport(data) {
  if (!data || typeof data.imported !== "boolean") return false;
  if (!data.imported) return true;
  return (
    isValidSource(data.source) &&
    typeof data.raw_posting === "string" &&
    data.raw_posting.trim().length > 0 &&
    Array.isArray(data.checks) &&
    data.checks.every(isValidCheck)
  );
}

// POST /import-url -> the page text, where it came from, and the verification checks. The model is NOT run here:
// the caller sends `raw_posting` to analyzePosting(), so one analysis makes exactly one model prediction.
// A page that cannot be imported returns { imported: false } (not an exception) so the page can offer "Switch to Paste".
export async function importJobUrl({ url, companyWebsite, recruiterEmail }) {
  const response = await postJson("/import-url", {
    url,
    company_website: companyWebsite || null,
    recruiter_email: recruiterEmail || null,
  });
  const body = await readJson(response);

  if (response.status === 422) throw new ApiError(BAD_URL_MESSAGE, "validation");
  if (!response.ok || !isValidImport(body)) throw new ApiError(GENERIC_MESSAGE, "server");
  return body;
}

// POST /extract -> how the pasted text splits into sections. Rule-based; the model is not involved.
export async function extractDetails(rawPosting) {
  const response = await postJson("/extract", { raw_posting: rawPosting });
  const body = await readJson(response);
  if (!response.ok || !isValidExtraction(body)) throw new ApiError(GENERIC_MESSAGE, "server");
  return body;
}
