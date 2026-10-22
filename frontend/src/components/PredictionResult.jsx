// Shows the backend's answer. Nothing here decides fraud: `result.prediction` comes from FastAPI.
//
// The result has independent parts, shown in separate cards:
//   1. the DistilBERT risk score (machine learning)
//   2. the warning signs (plain text rules, with quotes from the posting)
//   3. verification of the job link and contact details (only when the job came from a URL)
// None of them explains or changes another: the signs do not explain the score, and verification feeds neither.

import { forwardRef } from "react";
import SignalPanel from "./SignalPanel.jsx";
import VerificationPanel from "./VerificationPanel.jsx";

// General safety advice. It is the same for every posting with that outcome and does NOT explain the model's decision.
const NEXT_STEPS = {
  fraudulent: {
    heading: "What should I do next?",
    items: [
      "Verify the opening on the employer’s official careers website.",
      "Do not pay money to obtain a job.",
      "Do not send banking or identity details before verifying the employer and hiring process.",
      "Contact the employer through contact information you independently find.",
      "Search the company or recruiter name plus terms such as “scam”, “review” or “complaint”.",
    ],
  },
  legitimate: {
    heading: "Still verify before applying",
    items: [
      "Confirm the job on the official company site.",
      "Check the recruiter’s identity and email domain.",
      "Be cautious with sensitive data such as banking or identity details.",
      "Never pay to get a job.",
    ],
  },
};

const FTC_JOB_SCAMS = "https://consumer.ftc.gov/articles/job-scams";
const FTC_TASK_SCAMS = "https://consumer.ftc.gov/consumer-alerts/2025/08/how-spot-avoid-task-scams";

const PredictionResult = forwardRef(function PredictionResult({ result, verification, onReset }, ref) {
  const isFraud = result.prediction === "fraudulent";
  const steps = NEXT_STEPS[result.prediction];
  // Backend gives e.g. 98.91; show one decimal place.
  const percent = result.fraud_percentage;
  const percentText = `${percent.toFixed(1)}%`;
  // An older backend may not send warning signs; then that section is simply not shown.
  const signals = Array.isArray(result.signals) ? result.signals : null;

  return (
    <div ref={ref} tabIndex={-1} className="result-stack" role="region" aria-labelledby="result-heading">
      {/* ---------- Part 1: the DistilBERT risk score ---------- */}
      <section className={`card result-card ${isFraud ? "result-fraud" : "result-legit"}`}>
        <div className="result-main">
          {/* Icon + text, so the outcome never depends on color alone */}
          <div className="result-verdict">
            <span className="result-icon" aria-hidden="true">
              {isFraud ? "!" : "✓"}
            </span>
            <div>
              <p className="result-kicker">{result.model} risk assessment</p>
              <h2 id="result-heading">{result.label}</h2>
            </div>
          </div>

          <div className="result-score">
            <p className="score-label">Fraud Risk</p>
            <p className="score-value">{percentText}</p>
          </div>
        </div>

        {/* The bar only draws fraud_percentage; it adds no thresholds of its own. */}
        <div
          className="risk-bar"
          role="progressbar"
          aria-label="Fraud risk"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(percent * 10) / 10}
          aria-valuetext={`Fraud risk ${percentText}`}
        >
          <div className="risk-bar-fill" style={{ width: `${percent}%` }} />
        </div>
        <p className="score-caption">A risk score from the model. It is a signal to check further, not proof.</p>
      </section>

      {/* ---------- Part 2: the warning signs (separate system) ---------- */}
      {signals && <SignalPanel signals={signals} />}

      {/* ---------- Part 3: verification of the link and contact details (URL analyses only; separate system) ---------- */}
      {verification && (
        <VerificationPanel
          source={verification.source}
          checks={verification.checks}
          importedText={verification.importedText}
        />
      )}

      {/* ---------- What to do ---------- */}
      <section className="card next-card" aria-labelledby="next-heading">
        <h3 id="next-heading">{steps.heading}</h3>
        <ul>
          {steps.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="next-steps-note">General safety tips for any posting. They do not explain the model’s score.</p>
      </section>

      {/* ---------- How the three parts differ (URL analyses) ---------- */}
      {verification && (
        <section className="how-result" aria-labelledby="what-this-means-heading">
          <h3 id="what-this-means-heading">What this means</h3>
          <dl className="how-result-list">
            <div>
              <dt>Machine-learning risk</dt>
              <dd>Patterns learned from historical fake and legitimate job postings.</dd>
            </div>
            <div>
              <dt>Warning signs</dt>
              <dd>Transparent text rules for common employment-scam patterns.</dd>
            </div>
            <div>
              <dt>Verification</dt>
              <dd>Checks whether domains, URLs and contact information are internally consistent.</dd>
            </div>
          </dl>
          <p>
            None of these alone proves whether a job is legitimate. They are independent: verification never changes the
            risk score or the warning signs.
          </p>
        </section>
      )}

      {/* ---------- How the two parts differ (pasted postings) ---------- */}
      {!verification && signals && (
        <section className="how-result" aria-labelledby="how-result-heading">
          <h3 id="how-result-heading">How this result works</h3>
          <dl>
            <div>
              <dt>DistilBERT risk score</dt>
              <dd>A machine-learning model trained to distinguish fraudulent and legitimate job postings.</dd>
            </div>
            <div>
              <dt>Warning signs</dt>
              <dd>Transparent text checks for common employment-scam patterns.</dd>
            </div>
          </dl>
          <p>These systems are independent. The warning signs do not explain the risk score, and the score is not built from them.</p>
        </section>
      )}

      <p className="result-disclaimer">{result.disclaimer}</p>

      {/* ---------- Where the safety guidance comes from ---------- */}
      <p className="safety-source">
        Safety guidance informed by public FTC job-scam recommendations (
        <a href={FTC_JOB_SCAMS} target="_blank" rel="noopener noreferrer">
          Job Scams
        </a>
        ,{" "}
        <a href={FTC_TASK_SCAMS} target="_blank" rel="noopener noreferrer">
          Task scams
        </a>
        ). JobGuard is an independent student project and is not affiliated with or endorsed by the FTC.
      </p>

      <div className="result-footer">
        <p className="result-model">Analyzed with {result.model}</p>
        <button type="button" className="btn btn-secondary" onClick={onReset}>
          Analyze another posting
        </button>
      </div>
    </div>
  );
});

export default PredictionResult;
