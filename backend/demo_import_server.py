"""DEMONSTRATION server: the real JobGuard API, with the internet replaced by a few hand-written job pages.

    python -m backend.demo_import_server

Why this exists: the real importer refuses localhost and private addresses (that is the point of its safety checks),
so a controlled test page served from this computer can never be imported. This script starts the normal API
(real DistilBERT model, real scanner, real verification) but points ONLY the page-fetching step at the canned pages
in backend/demo_pages.py. It is for demos and manual testing. Never use it as the production server: use
`uvicorn backend.main:app` for that.

Pages you can paste into "Job URL":
    https://careers.northwind-analytics.com/jobs/software-engineer     (company page with JobPosting data)
    https://boards.greenhouse.io/northwind/jobs/4012345                (recruiting platform, redirects inside it)
    https://short.example-links.com/r/3fK9                             (short link -> plain-HTTP page, other domain)
    https://www.job-board-example.com/view/991                         (answers 403: import stops gracefully)
    https://spa.job-board-example.org/jobs/55                          (needs JavaScript: nothing to read)
"""

import uvicorn

from backend import url_importer
from backend.demo_pages import build_demo_web

web = build_demo_web()
url_importer.use_fake_network_for_demo(resolver=web.resolver, transport=web.transport())

from backend.main import app  # noqa: E402  (imported after the fake network is installed)

if __name__ == "__main__":
    print("DEMO MODE: page fetching is replaced by canned pages. Not the production server.")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
