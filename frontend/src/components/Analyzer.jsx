// The main action of the page: give JobGuard a job posting and press Analyze Job.
// Two input modes: paste the posting text (the default), or give a job URL.
// This is a "controlled" component: App owns every value, this component only shows them.

import DetectedDetails from "./DetectedDetails.jsx";
import UrlPanel from "./UrlPanel.jsx";
import { EXAMPLES } from "../examples.js";

const PLACEHOLDER =
  "Paste the full posting here — title, company information, description, requirements, benefits, compensation, or anything else included in the listing.";

const MODES = [
  { id: "paste", label: "Paste Job Posting" },
  { id: "url", label: "Job URL" },
];

function Analyzer({
  mode,
  onModeChange,
  rawText,
  urlForm,
  detailsOpen,
  onToggleVerificationDetails,
  onUrlChange,
  importFailed,
  onSwitchToPaste,
  loading,
  error,
  onRawChange,
  onSubmit,
  onClear,
  onExample,
  details,
  reading,
  stale,
  fields,
  edited,
  reviewOpen,
  onToggleReview,
  onFieldChange,
  onRestore,
}) {
  const isExample = Object.values(EXAMPLES).includes(rawText);
  const hasInput = mode === "paste" ? Boolean(rawText) : Boolean(urlForm.url || urlForm.company || urlForm.email);

  // Arrow keys move between the two tabs, as users expect from tabs.
  function handleTabKey(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = mode === "paste" ? "url" : "paste";
    onModeChange(next);
    document.getElementById(`tab-${next}`)?.focus();
  }

  return (
    <form id="analyzer" className="card analyzer-card" onSubmit={onSubmit} noValidate>
      <div className="mode-tabs" role="tablist" aria-label="How do you want to add the job?" onKeyDown={handleTabKey}>
        {MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={mode === item.id}
            aria-controls={`panel-${item.id}`}
            tabIndex={mode === item.id ? 0 : -1}
            className={mode === item.id ? "mode-tab is-active" : "mode-tab"}
            onClick={() => onModeChange(item.id)}
            disabled={loading}
          >
            {item.label}
          </button>
        ))}
      </div>

      {mode === "paste" ? (
        <div role="tabpanel" id="panel-paste" aria-labelledby="tab-paste">
          <div className="paste-head">
            <label htmlFor="raw-posting" className="paste-label">
              Paste job posting
            </label>
            <div className="examples" role="group" aria-label="Try an example">
              <span className="examples-label">Try an example:</span>
              <button type="button" className="chip" onClick={() => onExample("professional")} disabled={loading}>
                Professional posting
              </button>
              <button type="button" className="chip" onClick={() => onExample("suspicious")} disabled={loading}>
                Suspicious posting
              </button>
            </div>
          </div>

          <textarea
            id="raw-posting"
            className={error ? "paste-box has-error" : "paste-box"}
            value={rawText}
            onChange={onRawChange}
            placeholder={PLACEHOLDER}
            rows={12}
            disabled={loading}
            aria-invalid={error ? "true" : undefined}
            aria-describedby={error ? "analyzer-error" : undefined}
          />
          {isExample && <p className="example-note">A hand-written demonstration posting, not a real job.</p>}

          {/* Shown right above the button so the message is next to the action that caused it */}
          {error && (
            <p id="analyzer-error" className="error-banner" role="alert">
              <span aria-hidden="true">⚠ </span>
              {error}
            </p>
          )}

          {rawText.trim() && (
            <DetectedDetails
              details={details}
              reading={reading}
              stale={stale}
              fields={fields}
              edited={edited}
              open={reviewOpen}
              disabled={loading}
              onToggle={onToggleReview}
              onFieldChange={onFieldChange}
              onRestore={onRestore}
            />
          )}
        </div>
      ) : (
        <UrlPanel
          urlForm={urlForm}
          loading={loading}
          error={error}
          importFailed={importFailed}
          detailsOpen={detailsOpen}
          onChange={onUrlChange}
          onToggleDetails={onToggleVerificationDetails}
          onSwitchToPaste={onSwitchToPaste}
        />
      )}

      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={loading} aria-busy={loading}>
          {loading ? (
            <>
              <span className="spinner" aria-hidden="true" />
              Analyzing…
            </>
          ) : (
            "Analyze Job"
          )}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClear} disabled={loading || !hasInput}>
          Clear
        </button>
      </div>

      <p className="card-foot">
        Powered by DistilBERT. JobGuard gives a risk signal, not proof that a posting is real or fake.
      </p>
    </form>
  );
}

export default Analyzer;
