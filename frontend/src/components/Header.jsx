// Top of the page: brand and one clear promise. The paste box (Analyzer) sits right below.

function ShieldIcon() {
  return (
    <svg className="brand-icon" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M16 2 4 6.5v8.6c0 7.2 5 12.4 12 14.9 7-2.5 12-7.7 12-14.9V6.5L16 2z" fill="currentColor" />
      <path
        d="m10.5 16.2 3.9 3.9 7.2-7.6"
        fill="none"
        stroke="#0f1b33"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Header() {
  return (
    <header className="hero">
      <div className="container">
        <div className="brand">
          <ShieldIcon />
          <span className="brand-name">JobGuard AI</span>
        </div>

        <h1>Check a job before you apply.</h1>
        <p className="hero-text">
          Paste the full job posting below, or give JobGuard a link to it. JobGuard analyzes its language for
          patterns commonly associated with fraudulent job advertisements.
        </p>
      </div>
    </header>
  );
}

export default Header;
