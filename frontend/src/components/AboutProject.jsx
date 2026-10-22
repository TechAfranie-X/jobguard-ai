function AboutProject() {
  return (
    <section className="section" aria-labelledby="about-heading">
      <h2 id="about-heading" className="section-title">
        About the project
      </h2>
      <div className="card about-card">
        <p>
          JobGuard AI is an undergraduate machine-learning project. The model was trained on EMSCAD, a public
          dataset of labeled job postings, and fine-tuned from DistilBERT.
        </p>
        <h3 className="sub-title">Good to know</h3>
        <ul className="about-list">
          <li>JobGuard gives a risk signal, not proof. Always verify an employer yourself.</li>
          <li>It was trained on one dataset, so it can miss new kinds of scams. In our test it missed about one in four.</li>
          <li>Long postings are shortened for the model, which reads roughly the first 256 tokens.</li>
          <li>
            Warning signs come from fixed text rules, not from the model. They can miss things, they can point at
            harmless wording, and finding none does not mean a posting is safe.
          </li>
          <li>
            Some job sites block automated access or need JavaScript, so a link cannot always be imported. Pasting the
            posting always works.
          </li>
          <li>
            Verification checks compare web addresses and email domains. A match does not prove a job is real, and a
            difference does not prove it is fake. JobGuard does not currently store analyses.
          </li>
          <li>It is built for job postings. It is not designed for recruiter messages or offer letters.</li>
        </ul>
      </div>
    </section>
  );
}

export default AboutProject;
