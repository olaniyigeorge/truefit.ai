# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this repository, please **do not** open a public issue.
Instead, email **[olaniyigeorge77@gmail.com]** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

We will respond within 48 hours and work with you to resolve the issue responsibly.

---

## Note on Automated Credential Scans

This repository may trigger automated credential scanners on the following files:

| File | Finding | Status |
|------|---------|--------|
| `OAUTH_AUTHENTICATION_DOCS.md` | `curl-auth-header`, `generic-api-key` |  False positive — placeholder/example values only |

All values flagged are documentation placeholders (e.g. `$TOKEN`, `<generate-with-python-secrets>`).
**No real credentials have ever been committed to this repository.**

This was verified by:
- Inspecting the flagged file contents directly
- Running `git log --all --full-history` — no `.env` or secret files in history

---

## Secrets Management

Real credentials for this project are managed via:
- **Environment variables** written directly to the GCP Compute Engine VM (not committed to git)
- **Firebase Console** for Firebase service account credentials
- **Planned:** Migrating to [GCP Secret Manager](https://cloud.google.com/secret-manager) for all production secrets as a security hardening step


The `.env.example` file in `apps/backend/` contains only placeholder values safe for public viewing.