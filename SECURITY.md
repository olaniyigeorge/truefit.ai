# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this repository, please **do not** open a public issue.

Email **olaniyigeorge77@gmail.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

We will respond within 48 hours and work with you to resolve the issue responsibly before any public disclosure.

---

## Secrets Management

Real credentials for this project are managed as follows:

- **Environment variables** written directly to the GCP Compute Engine VM — never committed to git
- **Firebase credentials** managed via the Firebase Console
- **Planned:** migration to [GCP Secret Manager](https://cloud.google.com/secret-manager) for all production secrets

The `.env.example` file in `apps/backend/` contains only placeholder values safe for public viewing. No real credentials have ever been committed to this repository.

---

## Note on Automated Credential Scans

This repository may trigger automated credential scanners on documentation files. Known false positives:

| File | Finding | Status |
|------|---------|--------|
| `docs/auth.md` | `curl-auth-header`, `generic-api-key` | False positive — placeholder/example values only |

All flagged values are documentation placeholders (e.g. `$TOKEN`, `eyJhbGc...`). This has been verified by inspecting flagged file contents and reviewing full git history.

---

## Security Checklist (for maintainers)

- [ ] `APP_SECRET_KEY` is 32+ characters, randomly generated, and never reused across environments
- [ ] `.env` files with real secrets are in `.gitignore` and never committed
- [ ] CORS is restricted to the production frontend domain in production deployments
- [ ] Firebase project ID matches the correct environment (dev vs prod)
- [ ] Auth endpoints have rate limiting before going to production
- [ ] HTTPS is enforced in production