// Static project information: final test metrics and the four-model comparison.
// These numbers were produced by the Milestone 8 evaluation on the held-out test set
// (results/metrics/final_test_model_comparison.csv). They are typed in here only for display.

const FINAL_METRICS = [
  {
    name: "Fraud precision",
    value: "88.43%",
    help: "When JobGuard flagged a posting in our test data, how often the flag was right.",
  },
  {
    name: "Fraud recall",
    value: "74.31%",
    help: "How many of the fraudulent postings in our test data were caught.",
  },
  {
    name: "Fraud F1",
    value: "80.75%",
    help: "A single score that balances precision and recall.",
  },
];

const COMPARISON = [
  { model: "Logistic Regression", f1: 70.45 },
  { model: "Naive Bayes", f1: 71.65 },
  { model: "XGBoost", f1: 75.0 },
  { model: "DistilBERT", f1: 80.75, selected: true },
];

function ModelPerformance() {
  return (
    <section className="section" aria-labelledby="performance-heading">
      <h2 id="performance-heading" className="section-title">
        Model performance
      </h2>
      <p className="section-intro">
        Four approaches were compared on the same held-out test data. DistilBERT scored best and powers JobGuard.
      </p>

      <div className="metrics">
        {FINAL_METRICS.map((m) => (
          <div key={m.name} className="metric">
            <p className="metric-name">{m.name}</p>
            <p className="metric-value">{m.value}</p>
            <p className="metric-help">{m.help}</p>
          </div>
        ))}
      </div>

      <div className="card compare-card">
        <h3 className="sub-title">Fraud F1 by model</h3>
        <ul className="compare-list">
          {COMPARISON.map((c) => (
            <li key={c.model} className={c.selected ? "compare-item selected" : "compare-item"}>
              <div className="compare-head">
                <span className="compare-name">
                  {c.model}
                  {c.selected && <span className="compare-tag">Selected</span>}
                </span>
                <span className="compare-value">{c.f1.toFixed(2)}%</span>
              </div>
              <div className="compare-bar" aria-hidden="true">
                <div className="compare-bar-fill" style={{ width: `${c.f1}%` }} />
              </div>
            </li>
          ))}
        </ul>
        <p className="muted">
          Test set: 3,214 postings, 144 of them fraudulent. Overall accuracy was 98.41%, but only about 4.5% of
          postings are fraudulent, so precision, recall and F1 say more.
        </p>
      </div>
    </section>
  );
}

export default ModelPerformance;
