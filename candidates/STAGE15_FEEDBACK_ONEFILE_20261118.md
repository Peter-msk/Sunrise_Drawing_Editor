# Stage15 — Feedback and Onefile notices / update candidate

Parent: e29fb82445d0dce4bb6f2e4a707f36b344b4242d (Stage14). Status: source candidate; not approved for production.

- Known independent defect: large opaque PNG trim used RGBA detection while small opaque PNG uses RGB. On synthetic painted white sheet, alpha bbox includes invisible white paper. Scan actual RGB for opaque large crop; transparent path unchanged.
- Four distinct synthetic PDFs with per-file OCG OFF, isolated batch, exact RGB crop and single-vs-batch comparison regression added. Actual user four original PDFs still required.
- Notice and update feed contract (`notice.txt` / `latest.json`), proposed initial numeric version 1.0.0; network fetch limited to fixed HTTPS product endpoints, no redirect, plain text, bounded body, offline failure not an update. Only frozen GUI automatically checks; existing worker/self-test routes continue to bypass network.
- Update notification only opens official release page and closes application; binary download/hash/signature verification and self-replacement transaction are NOT implemented. No live EXE metadata enabled.
- Mark hiding not implemented: inspect actual PDF OCG, locked object and attribution terms first; do not bypass locks or alter source.
- Preserve existing signing/build and no full redundant regression by default. Windows runtime, GUI, PyInstaller and sign checks NOT RUN; actual user source data NOT RUN.
- No claim of successful release. Run focused tests: python -m unittest discover -s tests -p "test_release_feed.py" -v ; python -m unittest discover -s tests -p "test_feedback_four_sheet_crop.py" -v

## Second source iteration

Added disabled-by-default user-approved Onefile self-replacement candidate. Fixed product release URL, HTTPS redirect allowlist, exact byte count + SHA-256, Windows WinVerifyTrust with actual validated Sunrise Group leaf fingerprint equal to running executable, candidate smoke before handoff, independent PyInstaller process, wait for process exit, same-volume atomic swap, backup and restart failure rollback. No automatic update until `automatic_update_available=true` in validated release metadata after Windows QA. Untrusted self-signing and certificate rollover require manual handling; no trust-store edits. Native Windows execution, real signed binary, restart/rollback, cancellation and cleanup soak are NOT RUN. Temporary rollback remains until user verifies release; automatic stale-stage cleanup is not yet implemented. Prior statement of missing self-replacement describes first iteration only.
Native API reference: https://learn.microsoft.com/en-us/windows/win32/api/Wintrust/nf-wintrust-winverifytrust ; https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-wthelpergetprovcertfromchain .
