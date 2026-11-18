# Stage15 — Feedback and Onefile notices / update candidate

Parent: e29fb82445d0dce4bb6f2e4a707f36b344b4242d (Stage14). Status: source candidate; not approved for production.

- Known independent defect: large opaque PNG trim used RGBA detection while small opaque PNG uses RGB. On synthetic painted white sheet, alpha bbox includes invisible white paper. Scan actual RGB for opaque large crop; transparent path unchanged.
- Four distinct synthetic PDFs with per-file OCG OFF, isolated batch, exact RGB crop and single-vs-batch comparison regression added. Actual user four original PDFs still required.
- Notice and update feed contract (`notice.txt` / `latest.json`), proposed initial numeric version 1.0.0; network fetch limited to fixed HTTPS product endpoints, no redirect, plain text, bounded body, offline failure not an update. Only frozen GUI automatically checks; existing worker/self-test routes continue to bypass network.
- Update notification only opens official release page and closes application; binary download/hash/signature verification and self-replacement transaction are NOT implemented. No live EXE metadata enabled.
- Mark hiding not implemented: inspect actual PDF OCG, locked object and attribution terms first; do not bypass locks or alter source.
- Preserve existing signing/build and no full redundant regression by default. Windows runtime, GUI, PyInstaller and sign checks NOT RUN; actual user source data NOT RUN.
- No claim of successful release. Run focused tests: python -m unittest discover -s tests -p "test_release_feed.py" -v ; python -m unittest discover -s tests -p "test_feedback_four_sheet_crop.py" -v
