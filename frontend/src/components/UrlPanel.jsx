// The "Job URL" input mode: a job link, plus two OPTIONAL details used for verification checks.
// This is a controlled component: App owns every value. Nothing typed here is stored anywhere.

function UrlPanel({
  urlForm,
  loading,
  error,
  importFailed,
  detailsOpen,
  onChange,
  onToggleDetails,
  onSwitchToPaste,
}) {
  return (
    <div role="tabpanel" id="panel-url" aria-labelledby="tab-url">
      <label htmlFor="job-url" className="paste-label url-label">
        Job posting URL
      </label>
      <p className="url-help">JobGuard opens the public page, reads the job text and analyzes it. Nothing is stored.</p>

      <input
        id="job-url"
        name="url"
        type="text"
        inputMode="url"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        className={error ? "text-input has-error" : "text-input"}
        value={urlForm.url}
        onChange={onChange}
        placeholder="https://company.com/careers/software-engineer"
        disabled={loading}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={error ? "analyzer-error" : undefined}
      />

      {error && (
        <p id="analyzer-error" className="error-banner" role="alert">
          <span aria-hidden="true">⚠ </span>
          {error}
        </p>
      )}

      {/* The product should never look broken: a blocked or unreadable page gets a clear next step. */}
      {importFailed && (
        <div className="import-failure" role="alert">
          <p className="import-failure-title">
            <span aria-hidden="true">⚠ </span>We couldn’t import this job page automatically.
          </p>
          <p>Some job sites block automated access. Copy the posting and paste it instead.</p>
          <button type="button" className="btn btn-secondary" onClick={onSwitchToPaste}>
            Switch to Paste
          </button>
        </div>
      )}

      <div className="verify-details">
        <button
          type="button"
          className="link-button"
          aria-expanded={detailsOpen}
          aria-controls="verify-fields"
          onClick={onToggleDetails}
        >
          Add verification details
          <span className="optional-tag">optional</span>
          <span aria-hidden="true" className={detailsOpen ? "chevron is-open" : "chevron"} />
        </button>

        {detailsOpen && (
          <div id="verify-fields" className="verify-fields">
            <p className="review-intro">
              Adding these helps JobGuard compare where the job is hosted and whether recruiter contact information
              matches the company. You can analyze a job URL without them.
            </p>

            <div className="field">
              <label htmlFor="company-website">Company website (optional)</label>
              <input
                id="company-website"
                name="company"
                type="text"
                inputMode="url"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                className="text-input"
                value={urlForm.company}
                onChange={onChange}
                placeholder="https://company.com"
                disabled={loading}
              />
            </div>

            <div className="field">
              <label htmlFor="recruiter-email">Recruiter email (optional)</label>
              <input
                id="recruiter-email"
                name="email"
                type="text"
                inputMode="email"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                className="text-input"
                value={urlForm.email}
                onChange={onChange}
                placeholder="recruiter@company.com"
                disabled={loading}
              />
            </div>

            <p className="verify-privacy">
              Only a web address and an email address are needed. Please don’t enter passwords, Social Security
              numbers, banking information or identity documents. JobGuard does not open the company website; it only
              compares the names.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default UrlPanel;
