# Job URL Import and Identity Verification (Milestone 14)

Until Milestone 13, JobGuard answered one question: **"What does this job posting say?"** (DistilBERT risk score plus rule-based warning signs).
Milestone 14 adds a third, separate layer that looks at **where the posting lives and whether the contact details line up**, and a way to give JobGuard a job link instead of pasting text.

```
User
 ↓
Paste Job ───────────────┐
                         │
Job URL → Safe Importer ─┤
                         ↓
                  Smart Intake
                     /       \
                    /         \
          DistilBERT        Scam Signals
                    \         /
                     \       /
                  Verification
                       ↓
                 Unified Result
```

The three layers are independent. **Verification uses URL and contact metadata only. It never feeds the model, never changes the warning signs, and the model never sees it.** Importing a URL ends with exactly the same text the user could have pasted, and that text goes through the same Smart Intake Parser, the same `create_combined_text` and the same DistilBERT call (threshold 0.5, `max_length` 256) as any pasted posting.

What did not change: model weights, threshold, `max_length`, preprocessing, the intake parser, the scam scanner, `test.csv` (not used), the final metrics. No generative AI or external API is used anywhere.

## What the user does

1. Choose **Job URL** (the default is still **Paste Job Posting**).
2. Enter the job link. Optionally open **Add verification details** and enter the company website and/or a recruiter email.
3. Press **Analyze Job**. One action: the page imports the job, analyzes it and shows the unified result.

If the page cannot be imported, the user sees "We couldn't import this job page automatically. Some job sites block automated access. Copy the posting and paste it instead." and a **Switch to Paste** button. The link stays in the Job URL tab.

## How a URL becomes a result

```
POST /import-url   (backend/url_importer.py + backend/verification.py; no model)
  validate URL -> resolve + check addresses -> fetch (limits, manual redirects) -> extract text
  -> Smart Intake Parser (the existing one, only to organise the text) -> raw_posting
  -> verification checks (from URL and typed details only)
frontend, same click
POST /predict      (the existing endpoint: smart intake -> combined_text -> DistilBERT -> scam signals)
```

`/import-url` deliberately does **not** run DistilBERT. The frontend sends the returned `raw_posting` to the normal `/predict`, so there is no second copy of the ML code and exactly one model inference per analysis. The verification checks are shown beside the result and are never sent to `/predict`.

`POST /import-url` request: `{"url": "...", "company_website": null | "...", "recruiter_email": null | "..."}`.
Response: `imported` (true/false), `message`, `reason` (failure only), `source` (`requested_url`, `final_url`, `source_domain`, `redirect_count`, `https`, `structured_job_data_found`, `page_title`, `company_name`), `raw_posting`, `extracted_fields`, `checks`, `timings_ms`. A page that cannot be imported is a normal `200` with `imported: false`, never a stack trace.

## Security: why a "fetch this URL" feature is dangerous, and what stops it

A server that fetches user-supplied URLs can be tricked into calling things the user should never reach (a classic **SSRF**, server-side request forgery): the machine's own services (`localhost`), the home or office network (`192.168.x.x`), or cloud metadata services (`169.254.169.254`). All checks below happen in `backend/url_importer.py` **before** any request is made.

| Safeguard | Behavior |
|---|---|
| Scheme | Only `http` and `https`. `file:`, `ftp:`, `data:`, `javascript:` and any other scheme are rejected. |
| Credentials | `user:password@host` URLs are rejected. |
| Ports | Only 80 and 443. |
| Host names | `localhost`, `.local`, `.localhost`, `.internal`, `.localdomain`, `.lan`, `.home.arpa`, `.intranet`, `.corp`, `.home`, `.private`, single-label names and number-like names are rejected. IP-literal hosts are rejected outright. |
| Resolved addresses | The host name is resolved by JobGuard itself, and **every** address returned must be a public (globally routable) address. Loopback, private (RFC 1918), link-local (including the metadata address), reserved, multicast, unspecified, IPv4-mapped IPv6, and the 6to4, Teredo and NAT64 translation ranges are all rejected. One bad address among several rejects the whole host. |
| DNS rebinding | The request is sent to the **already-validated IP address**, with the original name in the `Host` header and as the TLS server name, so the name cannot be re-resolved to a different address after the check. Certificates are still verified against the real name (a wrong-host or expired certificate is refused). |
| Redirects | Followed manually, at most 4. **Every** `Location` is parsed and run through all of the checks above before it is requested. A public page that redirects to a private address is refused before that address is contacted. |
| Size and time | Connect timeout 5 s, read timeout 8 s, 20 s for the whole import. Maximum 2 MB of HTML, counted **after** decompression (a small compressed file that expands hugely is cut off). A `Content-Length` over the limit is refused before the body is read. |
| Content | Only `text/html` and `application/xhtml+xml`. PDFs, ZIP files, images, executables and other binary types are refused. |
| No ambient credentials | No cookies are stored or sent, no authentication, no proxy settings from the environment. A clear `JobGuardBot/1.0` User-Agent identifies the request. |
| No evasion | `401`, `403`, `407`, `429`, `451`, `999`, CAPTCHA pages, bot challenges and login walls make the import **stop** with the message above. JobGuard does not retry, rotate identities, or try to get around any block. |
| No browser engine | There is no Playwright, Selenium, Puppeteer or headless Chrome. Pages that only render with JavaScript are not imported; the user is asked to paste. |
| No leaking | Failure messages do not reveal internal addresses or why a private address was refused. The server log records only the failure reason, never the URL, email address or company name. (The HTTP client library's own request logging, which would print URLs, is turned off.) |

`backend/test_url_importer.py` covers the required cases (valid HTTPS page, JSON-LD page, HTML fallback, redirect to another public domain, too many redirects, non-HTML, oversized, timeout, 403, malformed URL, credentials, `localhost`, `127.0.0.1`, `::1`, RFC 1918, link-local, the metadata IP, public-to-private redirect) plus many more, almost all with a mocked network. Private and local destinations are asserted to be rejected **without any request being made**.

## Reading the page

1. **JSON-LD first.** If the page contains a schema.org `JobPosting` (handled inside a plain object, a `@graph`, or a list of types), JobGuard uses its `title`, `description`, `hiringOrganization.name`, `jobLocation`, `employmentType`, `baseSalary`, `datePosted` and `validThrough`. Missing properties are left out, never invented. The description is turned from HTML to text. The result is laid out as a title, then labeled lines, then "Job Description", so the existing parser sorts it into the five fields. The JSON-LD is used only if it has a title and a description of at least 80 characters.
2. **Visible text as the fallback.** Otherwise JobGuard keeps the visible text of the page: headings on their own lines, paragraphs, list items as "- " lines. It drops `script`, `style`, navigation, page-level header and footer, hidden elements and cookie banners, and prefers `<main>` when it holds at least half of the text. A page with less than 200 characters of text is treated as a JavaScript-only or login page.
3. The text then goes through the **existing Smart Intake Parser**. There is no second parser.

LinkedIn, Indeed and similar sites commonly block automated access; for them the result is the paste fallback, which is the intended behavior.

## The verification checks

Every check has `id`, `status`, `title`, `detail` (and a `result` code). Statuses are `confirmed`, `attention`, `info` and `not_checked`. There is **no verification score, trust score, domain score or legitimacy percentage**, and the words "safe", "unsafe", "legit" and "fraud" are not used as verdicts. The page orders the rows "worth checking" first, then consistent, info and not checked.

| Check | What it compares | Possible results |
|---|---|---|
| Company website vs job page | Registered domain of the job page against the company website you typed (see below). | `MATCH` (same registered domain), `KNOWN_ATS` (hosted on a recognized recruiting platform), `DIFFERENT_DOMAIN` (shown as "worth checking", **not** as fraud), `NOT_CHECKED` |
| Recruiter email | The email's domain against the company website, or the personal-provider list. | `MATCH`, `MISMATCH`, `PERSONAL_EMAIL`, `NOT_CHECKED` |
| Redirects | Original domain, final domain, redirect count. | "This link redirected to a different domain." when the registered domain changed (info) |
| HTTPS | Whether the final page used HTTPS. | "Page loaded over HTTPS" (info) or "This page is not using HTTPS." (worth checking) |
| Structured data | Whether a schema.org `JobPosting` was found. | "Structured job data detected" (info, with "Many recruiting platforms expose standardized job metadata.") |
| Lookalike domain | The recruiter email domain, and the job page domain (unless it is a known recruiting platform), against the company domain you typed; also a short list of often-imitated brands. | "Possible lookalike domain. Verify the domain manually." (worth checking) |
| Punycode | Domains containing `xn--` labels (internationalized names that can imitate others). | "Domain uses international (xn--) characters" (worth checking; many sites use them legitimately) |

**Registered-domain comparison.** The registered domain is found with `tldextract` using its **bundled public-suffix snapshot only**: it is configured to never download a list and to write no cache, so nothing is fetched while a request is served. `jobs.company.com` and `company.com` are the same registered domain; `company.com.evil.example` belongs to `evil.example`. Shared hosts such as `name.github.io` are not treated as one site.

**Known recruiting platforms.** A small, transparent list in `backend/verification.py`: Greenhouse (`boards.greenhouse.io`, `job-boards.greenhouse.io`), Lever (`jobs.lever.co`, `jobs.eu.lever.co`), Ashby (`jobs.ashbyhq.com`), Workday (`*.myworkdayjobs.com`, `*.myworkdaysite.com`), iCIMS (`*.icims.com`), SmartRecruiters (`jobs.smartrecruiters.com`, `careers.smartrecruiters.com`), Workable (`apply.workable.com`), BambooHR (`*.bamboohr.com`). The message is "Hosted on a recognized recruiting platform", never "Verified". Exact hosts and subdomain suffixes are matched, so `greenhouse.io.evil.example` is not on the list. Sources, checked in October 2026: Greenhouse support documentation, the Lever `postings-api` README, Ashby's job-board documentation, SmartRecruiters developer documentation, iCIMS community pages and third-party articles describing Workday's URL format. Workable and BambooHR are well-known public patterns that were not separately sourced.

**Personal email providers.** Gmail, Yahoo, Hotmail/Outlook, iCloud, ProtonMail and similar (the full dictionary is in the code). The message is: "This recruiter email uses a personal email provider. Recruiters representing established companies generally use a company domain. Verify the sender independently." It is never called fraud, because many small employers and genuine individual recruiters use personal addresses.

**Lookalike detection is deliberately conservative.** It flags a recruiter domain only when it differs from the company domain you typed by confusable characters (`0`/`o`, `1`/`i`/`l`, `rn`/`m`, `vv`/`w`, and so on), by a single typo in two reasonably long names (7+ characters, so `stripe.com` and `strike.com` are not flagged), by an added hyphen word or a recruiting word (`acme-careers`, `acmejobs`), or, for a short list of often-imitated brands, by confusable characters alone. A different top-level domain by itself is not flagged. It says "possible" and asks the user to check; it does not claim impersonation.

`backend/test_verification.py` checks, among others: `company.com` vs `jobs.company.com` match; vs `company.com.evil.test` different domain; `recruiter@company.com` vs `company.com` match; `recruiter@gmail.com` personal; `cornpany.com` vs `company.com` possible lookalike; unrelated domains different but never "fraud"; `xn--` worth checking; HTTPS info; HTTP worth checking. It also asserts that no verdict word appears, the checks are deterministic, and nothing touches the network.

## Limitations (please read)

- **None of these checks proves a job is legitimate, and none proves it is fake.** A matching domain can be spoofed, copied or compromised. A different domain is often perfectly normal (recruiting platforms, parent companies, agencies). Hosting on a known recruiting platform does not guarantee the employer is real, because anyone can open an account there. A personal email does not automatically mean a scam. HTTPS only means the connection is encrypted.
- JobGuard does **not** search the web for the employer, check company registries, read WHOIS or domain age, or open the company website. It only compares the names it is given.
- Third-party sites may block importing, and pages that need JavaScript cannot be read. That is expected; pasting always works.
- `robots.txt` is not consulted: JobGuard fetches only the single page a user asked for, once, and does not crawl.
- DNS resolution has no timeout of its own beyond the operating system's; the 20-second total limit applies to the connection and download stages.
- The company website you type is only parsed for its domain; it is never requested.
- Verification details are used in Job URL mode only. In Paste mode there is no link to compare.

## Privacy

JobGuard does not currently store analyses. There is no database. The pasted posting, the job URL, the company website and the recruiter email are held in memory for the duration of the request and in the browser page, and are not saved, logged or sent anywhere except to the JobGuard backend you are running. The form asks users not to enter passwords, Social Security numbers, banking information or identity documents; none of these are needed.

## Measured performance

Measured on the development Mac (Apple MPS), small controlled samples, October 2026. These are not benchmarks of a production service.

| Step | Sample | Result |
|---|---|---|
| Fetch a real public job page (network, TLS, download) | 18 imports of 6 real Greenhouse, Lever and Ashby pages | median 234 ms, range 57 to 1,533 ms (Lever median 502 ms, Greenhouse 213 ms, Ashby 76 ms) |
| Extract text from the HTML | same 18 imports | median 11 ms, range 5 to 27 ms |
| Smart Intake Parser on the extracted text | same 18 imports | median 0.2 ms, range 0.1 to 0.5 ms |
| Verification (all checks, all details supplied) | mean of 2,000 runs | 0.045 ms |
| DistilBERT `/predict` (warm, includes intake and scanner) | 15 runs on each of three imported pages | medians 8.2 to 10.9 ms; the very first request after server start was slower (about 250 ms) because of one-time warm-up |
| Browser, click to result on the controlled demo pages | 3 URL analyses, 1 blocked import and 1 paste analysis in the real UI (a single run each; too few for a median) | URL: 456 ms (first request after start, includes warm-up), 136 ms, 82 ms; blocked page: 7 ms to the failure message; paste: 154 ms |

The controlled demo pages are served from memory, so the last two rows exclude real network time. The expected time a user waits on a real page is therefore roughly the fetch time in the first row (usually a fraction of a second, occasionally 1 to 2 seconds) plus about 10 ms of model time plus rendering.

## How the demo and the tests avoid the real internet

The importer correctly refuses `localhost`, so a controlled test page on this machine cannot be fetched. `backend/demo_pages.py` holds a few hand-written pages and `backend/demo_import_server.py` starts the real API with only the network fetch replaced (a fake resolver and an in-memory HTTP transport). The real endpoints, real DistilBERT and real scanner run; only the page download is canned. Run it with `python -m backend.demo_import_server` (it prints a "DEMO MODE" banner). It is not the production server (`uvicorn backend.main:app`). The five `jobguard_v4_*.png` screenshots were taken against this demo server; the real-network measurements above use the real importer directly.

## Files

`backend/url_importer.py` (safe fetch and text extraction), `backend/verification.py` (the checks), `backend/schemas.py` and `backend/main.py` (`POST /import-url`), `backend/test_url_importer.py`, `backend/test_verification.py`, `backend/test_api.py` (integration), `backend/demo_pages.py` and `backend/demo_import_server.py` (controlled demo), frontend: `components/UrlPanel.jsx`, `components/VerificationPanel.jsx`, and changes in `Analyzer.jsx`, `PredictionResult.jsx`, `App.jsx`, `services/api.js`.
