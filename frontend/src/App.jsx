import { useEffect, useRef, useState } from "react";
import Header from "./components/Header.jsx";
import Analyzer from "./components/Analyzer.jsx";
import PredictionResult from "./components/PredictionResult.jsx";
import HowItWorks from "./components/HowItWorks.jsx";
import ModelPerformance from "./components/ModelPerformance.jsx";
import AboutProject from "./components/AboutProject.jsx";
import {
  analyzePosting,
  extractDetails,
  importJobUrl,
  ApiError,
  EMPTY_MESSAGE,
  EMPTY_URL_MESSAGE,
  GENERIC_MESSAGE,
} from "./services/api.js";
import { EXAMPLES } from "./examples.js";
import "./App.css";

const SECTION_NAMES = ["title", "company_profile", "description", "requirements", "benefits"];
const EMPTY_FIELDS = Object.fromEntries(SECTION_NAMES.map((name) => [name, ""]));

// The pasted text is read this long after the user stops typing or pasting.
const READ_DELAY_MS = 500;

function pickFields(details) {
  return Object.fromEntries(SECTION_NAMES.map((name) => [name, details[name]]));
}

const BLANK_URL_FORM = { url: "", company: "", email: "" };

function App() {
  // Two ways to give JobGuard a job: paste its text (the default) or give its URL. Each mode keeps its own input.
  const [mode, setMode] = useState("paste");

  // Job URL mode: the link, plus two OPTIONAL verification details. None of this is stored anywhere.
  const [urlForm, setUrlForm] = useState(BLANK_URL_FORM);
  const [verificationDetailsOpen, setVerificationDetailsOpen] = useState(false);
  const [importFailed, setImportFailed] = useState(false);
  const [stage, setStage] = useState("analyzing"); // "importing" while a URL is being read, then "analyzing"
  const [verification, setVerification] = useState(null); // { source, checks, importedText } for the current result

  // What the user pasted. This is the main input of paste mode; everything else is derived from it or secondary.
  const [rawText, setRawText] = useState("");

  // What the parser found, and the editable copy of it (only used if the user chooses to correct something).
  const [details, setDetails] = useState(null);
  const [detailsFor, setDetailsFor] = useState(""); // the pasted text that `details` was read from
  const [reading, setReading] = useState(false);
  const [fields, setFields] = useState(EMPTY_FIELDS);
  const [edited, setEdited] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [readAgain, setReadAgain] = useState(0); // bump to read the same text again (e.g. after a failed read)

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const inFlight = useRef(false); // blocks duplicate submissions even before React re-renders
  const resultRef = useRef(null);

  // Read the pasted text into sections shortly after the user stops typing. This only calls the rule-based
  // reader (/extract); the model is not involved. If it fails, the page still works: Analyze sends the text as is.
  useEffect(() => {
    if (!rawText.trim()) return undefined;
    let cancelled = false;
    const timer = setTimeout(async () => {
      setReading(true);
      try {
        const found = await extractDetails(rawText);
        if (cancelled) return;
        setDetails(found);
        setDetailsFor(rawText);
        setFields(pickFields(found));
        setEdited(false);
      } catch {
        if (!cancelled) setDetails(null);
      } finally {
        if (!cancelled) setReading(false);
      }
    }, READ_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [rawText, readAgain]);

  // After a result appears, move the view (and screen-reader focus) to it.
  useEffect(() => {
    if (result && resultRef.current) {
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      resultRef.current.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      resultRef.current.focus({ preventScroll: true });
    }
  }, [result]);

  function handleRawChange(event) {
    const value = event.target.value;
    setRawText(value);
    setEdited(false); // the pasted text is the source of truth again
    if (!value.trim()) {
      setDetails(null);
      setReading(false);
      setReviewOpen(false);
    }
    if (error) setError("");
  }

  function handleFieldChange(event) {
    const { name, value } = event.target;
    setFields((current) => ({ ...current, [name]: value }));
    setEdited(true);
    if (error) setError("");
  }

  function handleRestore() {
    if (details) setFields(pickFields(details));
    setEdited(false);
  }

  // The text to send: the user's corrected fields if they changed any, otherwise the pasted text itself.
  // Returns null when there is nothing to analyze.
  function buildPayload() {
    if (edited) {
      const trimmed = Object.fromEntries(SECTION_NAMES.map((name) => [name, fields[name].trim()]));
      return SECTION_NAMES.some((name) => trimmed[name]) ? trimmed : null;
    }
    const text = rawText.trim();
    return text ? { raw_posting: text } : null;
  }

  // Job URL mode: ONE button does everything. Import the page (+ verification checks), then send the imported text
  // to the same /predict endpoint a pasted posting uses. The model runs once, on the text only: the verification
  // checks are shown next to the result and are never part of the model's input.
  async function submitUrl() {
    const url = urlForm.url.trim();
    if (!url) {
      setError(EMPTY_URL_MESSAGE);
      document.getElementById("job-url")?.focus();
      return;
    }

    inFlight.current = true;
    setLoading(true);
    setStage("importing");
    try {
      const imported = await importJobUrl({
        url,
        companyWebsite: urlForm.company.trim(),
        recruiterEmail: urlForm.email.trim(),
      });
      if (!imported.imported) {
        setImportFailed(true); // a normal outcome: show the "Switch to Paste" help, not an error
        return;
      }

      setStage("analyzing");
      const prediction = await analyzePosting({ raw_posting: imported.raw_posting });
      setVerification({ source: imported.source, checks: imported.checks, importedText: imported.raw_posting });
      setResult(prediction);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : GENERIC_MESSAGE);
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (inFlight.current) return;

    setResult(null);
    setVerification(null);
    setError("");
    setImportFailed(false);

    if (mode === "url") {
      await submitUrl();
      return;
    }

    setStage("analyzing");
    const payload = buildPayload();
    if (!payload) {
      setError(EMPTY_MESSAGE);
      document.getElementById("raw-posting")?.focus();
      return;
    }

    inFlight.current = true;
    setLoading(true);
    try {
      setResult(await analyzePosting(payload));
      if (!details) setReadAgain((count) => count + 1); // the earlier read failed; the server is reachable now
    } catch (err) {
      setError(err instanceof ApiError ? err.message : GENERIC_MESSAGE);
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  // Back to a blank page: no reload.
  // It clears the mode you are in; the other mode keeps what you typed there.
  function handleClear() {
    setError("");
    setResult(null);
    setVerification(null);
    setImportFailed(false);

    if (mode === "url") {
      setUrlForm(BLANK_URL_FORM);
      setVerificationDetailsOpen(false);
    } else {
      setRawText("");
      setDetails(null);
      setReading(false);
      setFields(EMPTY_FIELDS);
      setEdited(false);
      setReviewOpen(false);
    }
    document.getElementById("analyzer")?.scrollIntoView({ block: "center" });
    document.getElementById(mode === "url" ? "job-url" : "raw-posting")?.focus({ preventScroll: true });
  }

  // Switching mode never carries a result, error or import message across: they belong to the other mode.
  function handleModeChange(next) {
    if (next === mode || inFlight.current) return;
    setMode(next);
    setResult(null);
    setVerification(null);
    setError("");
    setImportFailed(false);
  }

  // "Switch to Paste" after a failed import. The URL stays in the Job URL tab in case the user comes back.
  function handleSwitchToPaste() {
    handleModeChange("paste");
    setTimeout(() => document.getElementById("raw-posting")?.focus(), 0);
  }

  function handleUrlChange(event) {
    const { name, value } = event.target;
    setUrlForm((current) => ({ ...current, [name]: value }));
    if (error) setError("");
    if (importFailed) setImportFailed(false);
  }

  // Fill the paste box with a demonstration posting. It is not submitted automatically.
  function handleExample(name) {
    setRawText(EXAMPLES[name]);
    setEdited(false);
    setReviewOpen(false);
    setError("");
    setResult(null);
  }

  return (
    <>
      <Header />

      <main className="container main">
        <Analyzer
          mode={mode}
          onModeChange={handleModeChange}
          urlForm={urlForm}
          onUrlChange={handleUrlChange}
          detailsOpen={verificationDetailsOpen}
          onToggleVerificationDetails={() => setVerificationDetailsOpen((open) => !open)}
          importFailed={importFailed}
          onSwitchToPaste={handleSwitchToPaste}
          rawText={rawText}
          loading={loading}
          error={error}
          onRawChange={handleRawChange}
          onSubmit={handleSubmit}
          onClear={handleClear}
          onExample={handleExample}
          details={rawText.trim() ? details : null}
          reading={reading}
          stale={detailsFor !== rawText}
          fields={fields}
          edited={edited}
          reviewOpen={reviewOpen}
          onToggleReview={() => setReviewOpen((open) => !open)}
          onFieldChange={handleFieldChange}
          onRestore={handleRestore}
        />

        {/* role="status" is a live region, so screen readers announce loading. The result card receives
            keyboard focus when it appears, so it is read out as well. */}
        <div className="feedback">
          {loading && (
            <p className="loading-note" role="status">
              {stage === "importing" ? "Importing the job page…" : "Analyzing the posting…"}
            </p>
          )}
          {result && (
            <PredictionResult ref={resultRef} result={result} verification={verification} onReset={handleClear} />
          )}
        </div>

        <HowItWorks />
        <ModelPerformance />
        <AboutProject />
      </main>

      <footer className="footer">
        <div className="container">
          <p>JobGuard AI is an educational project. Results are risk signals, not proof.</p>
        </div>
      </footer>
    </>
  );
}

export default App;
