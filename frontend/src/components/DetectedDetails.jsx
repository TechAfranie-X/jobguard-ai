// "Detected details": what JobGuard found in the pasted text, with an optional panel to correct it.
// Progressive disclosure: the summary is always short; the editable fields only open on request.
// Nothing here is required. If the user never opens it, the pasted text is analyzed as it is.

const SECTIONS = [
  { name: "title", found: "Job title", missing: "Job title not found", label: "Job Title", input: true },
  {
    name: "company_profile",
    found: "Company information",
    missing: "Company information not found",
    label: "Company Profile",
    rows: 3,
  },
  { name: "description", found: "Description", missing: "Description not found", label: "Description", rows: 6 },
  { name: "requirements", found: "Requirements", missing: "Requirements not found", label: "Requirements", rows: 4 },
  { name: "benefits", found: "Benefits", missing: "Benefits not found", label: "Benefits", rows: 3 },
];

function DetectedDetails({ details, reading, stale, fields, edited, open, disabled, onToggle, onFieldChange, onRestore }) {
  if (!details) {
    // Shown only while the very first reading of a pasted text is in progress.
    return reading ? (
      <p className="detected-reading" role="status">
        Reading your posting…
      </p>
    ) : null;
  }

  const found = new Set(details.detected_sections);

  return (
    <div className={stale ? "detected is-stale" : "detected"} aria-busy={reading || stale || undefined}>
      <div className="detected-row">
        <div>
          <p className="detected-title">Detected details</p>
          <ul className="detected-list">
            {SECTIONS.map((s) => (
              <li key={s.name} className={found.has(s.name) ? "is-found" : "is-missing"}>
                <span aria-hidden="true">{found.has(s.name) ? "✓" : "—"}</span> {found.has(s.name) ? s.found : s.missing}
              </li>
            ))}
          </ul>
        </div>
        <button
          type="button"
          className="link-button"
          aria-expanded={open}
          aria-controls="review-panel"
          onClick={onToggle}
        >
          {open ? "Hide extracted details" : "Review extracted details"}
          <span aria-hidden="true" className={open ? "chevron is-open" : "chevron"} />
        </button>
      </div>

      {open && (
        <div id="review-panel" className="review-panel">
          <p className="review-intro">
            These details were read from your text. Fix anything that looks wrong, or leave them as they are.
            {edited ? " JobGuard will analyze your corrected version." : ""}
          </p>
          {details.fallback_used && (
            <p className="review-note">
              Any text JobGuard could not place in a section was kept in Description, so nothing you pasted is left out.
            </p>
          )}

          <div className="review-fields">
            {SECTIONS.map((s) => {
              const id = `review-${s.name}`;
              return (
                <div key={s.name} className="field">
                  <label htmlFor={id}>{s.label}</label>
                  {s.input ? (
                    <input
                      id={id}
                      name={s.name}
                      type="text"
                      value={fields[s.name]}
                      onChange={onFieldChange}
                      disabled={disabled}
                    />
                  ) : (
                    <textarea
                      id={id}
                      name={s.name}
                      rows={s.rows}
                      value={fields[s.name]}
                      onChange={onFieldChange}
                      disabled={disabled}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {edited && (
            <button type="button" className="link-button" onClick={onRestore} disabled={disabled}>
              Restore detected details
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default DetectedDetails;
