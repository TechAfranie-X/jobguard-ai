// Shows the warning signs found by the rule-based scanner (backend/scam_signals.py).
// These are plain text checks. They are NOT an explanation of the DistilBERT score and are shown separately from it.
// Every quote below is an exact excerpt of the pasted posting, produced by the backend.

import { useState } from "react";

// Severity is shown with a word AND a shape as well as a color, so it never depends on color alone.
const SEVERITY = {
  high: { word: "High", shape: "▲", className: "sev-high" },
  medium: { word: "Medium", shape: "◆", className: "sev-medium" },
  notice: { word: "Notice", shape: "●", className: "sev-notice" },
};

// Show the first few signs cleanly, but never hide a high-severity one.
const MIN_VISIBLE = 3;

function SignalCard({ signal }) {
  const severity = SEVERITY[signal.severity];
  const quotes = [signal.evidence, ...signal.more_evidence];
  const emails = signal.details?.emails ?? [];

  return (
    <li className={`signal-card ${severity.className}`}>
      <div className="signal-head">
        <span className="sev-badge">
          <span aria-hidden="true">{severity.shape}</span> {severity.word}
          <span className="visually-hidden"> severity</span>
        </span>
        <h4>{signal.title}</h4>
      </div>

      <p className="signal-found-label">Found in the posting</p>
      {quotes.map((quote) => (
        <blockquote key={quote} className="signal-evidence">
          “{quote}”
        </blockquote>
      ))}
      {emails.length > 0 && <p className="signal-detail">Address found: {emails.join(", ")}</p>}

      <p className="signal-explanation">{signal.explanation}</p>
      <p className="signal-action">
        <strong>What to do:</strong> {signal.recommended_action}
      </p>
    </li>
  );
}

function SignalPanel({ signals }) {
  const [showAll, setShowAll] = useState(false);
  const count = signals.length;
  const highCount = signals.filter((signal) => signal.severity === "high").length;

  // Signals arrive sorted high -> medium -> notice, so the first `visibleCount` include every high one.
  const visibleCount = Math.max(MIN_VISIBLE, highCount);
  const visible = signals.slice(0, visibleCount);
  const hidden = signals.slice(visibleCount);

  return (
    <section className="card signal-panel" aria-labelledby="signals-heading">
      <p className="part-label">Warning-sign scan · rule-based text checks</p>

      {count === 0 ? (
        <>
          <h3 id="signals-heading" className="signals-title">
            No common scam signals were detected in the text.
          </h3>
          <p className="signals-lead">
            This does not guarantee the posting is legitimate. JobGuard’s ML risk assessment and independent
            verification still matter.
          </p>
        </>
      ) : (
        <>
          <h3 id="signals-heading" className="signals-title">
            Warning signs found
          </h3>
          <p className="signals-count">
            {count} warning {count === 1 ? "sign" : "signs"} found
          </p>
          <p className="signals-lead">
            These are patterns worth verifying, quoted from the posting. A warning sign is not proof that a posting is
            fake.
          </p>

          <ul className="signal-list">
            {visible.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </ul>

          {hidden.length > 0 && (
            <>
              <ul className="signal-list signal-list-more" id="more-signals" hidden={!showAll}>
                {hidden.map((signal) => (
                  <SignalCard key={signal.id} signal={signal} />
                ))}
              </ul>
              <button
                type="button"
                className="btn btn-secondary signal-toggle"
                aria-expanded={showAll}
                aria-controls="more-signals"
                onClick={() => setShowAll((open) => !open)}
              >
                {showAll ? "Show fewer warning signs" : `View all warning signs (${count})`}
              </button>
            </>
          )}
        </>
      )}
    </section>
  );
}

export default SignalPanel;
