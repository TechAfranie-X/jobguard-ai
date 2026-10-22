const STEPS = [
  { title: "Paste or link", text: "Paste the full job posting, or enter the web address of a public job page." },
  {
    title: "Analyze",
    text: "A fine-tuned DistilBERT model estimates the fraud risk. Separately, simple text checks look for common scam warning signs.",
  },
  {
    title: "Review",
    text: "See the risk score, warning signs quoted from the posting, link and contact consistency checks (for a link), and what to verify next.",
  },
];

function HowItWorks() {
  return (
    <section className="section" aria-labelledby="how-heading">
      <h2 id="how-heading" className="section-title">
        How JobGuard works
      </h2>
      <ol className="steps">
        {STEPS.map((step, index) => (
          <li key={step.title} className="step">
            <span className="step-number" aria-hidden="true">
              {index + 1}
            </span>
            <h3>{step.title}</h3>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default HowItWorks;
