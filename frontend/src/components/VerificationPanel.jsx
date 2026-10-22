// Section B of a URL analysis: "Verification".
// These rows are FACTS about where the job page lives and whether the details the user typed are consistent
// (backend/verification.py). They are not a score and not a verdict, and they never feed the ML model.
// Every row has an icon AND a word, so the status never depends on color alone.

const STATUS = {
  attention: { icon: "!", word: "Worth checking", className: "check-attention" },
  confirmed: { icon: "✓", word: "Consistent", className: "check-confirmed" },
  info: { icon: "ⓘ", word: "Info", className: "check-info" },
  not_checked: { icon: "–", word: "Not checked", className: "check-not-checked" },
};

// Only ever link to a plain http(s) address (the backend already guarantees this; this is a second guard).
function safeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function VerificationPanel({ source, checks, importedText }) {
  const sourceHref = safeHttpUrl(source.final_url);

  return (
    <section className="card verify-card" aria-labelledby="verification-heading">
      <p className="part-label">Verification · link and contact consistency</p>
      <h3 id="verification-heading" className="signals-title">
        Verification
      </h3>
      <p className="signals-lead">
        Facts about where this job is hosted and whether the details you gave line up. They are not a verdict, and
        none of them proves a job is real or fake.
      </p>

      <p className="source-line">
        <span className="source-label">Source:</span> <strong>{source.source_domain}</strong>
        {sourceHref && (
          <a className="source-link" href={sourceHref} target="_blank" rel="noopener noreferrer">
            View source page <span aria-hidden="true">↗</span>
            <span className="visually-hidden"> (opens in a new tab)</span>
          </a>
        )}
      </p>

      <ul className="check-list">
        {checks.map((check) => {
          const status = STATUS[check.status];
          return (
            <li key={check.id} className={`check-item ${status.className}`}>
              <span className="check-icon" aria-hidden="true">
                {status.icon}
              </span>
              <div className="check-body">
                <p className="check-title">
                  {check.title} <span className="check-tag">{status.word}</span>
                </p>
                <p className="check-detail">{check.detail}</p>
              </div>
            </li>
          );
        })}
      </ul>

      {/* The full links and the imported text stay folded away unless the user asks for them. */}
      <details className="source-details">
        <summary>Source details</summary>
        <dl className="source-facts">
          <div>
            <dt>Link you entered</dt>
            <dd>{source.requested_url}</dd>
          </div>
          <div>
            <dt>Page that was read</dt>
            <dd>{source.final_url}</dd>
          </div>
          <div>
            <dt>Redirects followed</dt>
            <dd>{source.redirect_count}</dd>
          </div>
          <div>
            <dt>Connection</dt>
            <dd>{source.https ? "HTTPS" : "HTTP (not encrypted)"}</dd>
          </div>
        </dl>
        <p className="source-text-label">Text that was read from the page and analyzed</p>
        <pre className="source-text">{importedText}</pre>
      </details>
    </section>
  );
}

export default VerificationPanel;
