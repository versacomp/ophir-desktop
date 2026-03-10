# Security Policy

## Supported Versions

ophir-desktop is currently in early development (v0.0.x). Security fixes are applied to the latest version on `main`.

## Credential Handling

ophir-desktop reads API credentials exclusively from a local `.env` file that is listed in `.gitignore` and must never be committed to version control. The `.env.example` template shows the expected variable names with placeholder values.

**If you discover that credentials have been accidentally committed to a public repository:**

1. Revoke the exposed credentials immediately at [tastytrade API Access](https://my.tastytrade.com/app.html#/manage/api-access/oauth-applications).
2. Generate new credentials.
3. Remove the secrets from git history (e.g., with `git filter-repo`).

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report security issues privately by emailing the maintainer or using GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) feature if enabled on this repository.

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept (if safe to share)
- Your suggested fix or mitigation, if any

You can expect an acknowledgement within 72 hours and a resolution timeline within 14 days for confirmed issues.

## Scope

Issues considered in scope:
- Credential leakage or insecure storage
- Remote code execution via the built-in Python execution engine
- Authentication bypass in the OAuth2 flow
- Injection vulnerabilities in SQL or WebSocket handling

Issues considered out of scope:
- Financial losses from strategy use (see the disclaimer in [README.md](README.md))
- Vulnerabilities in third-party dependencies (report those upstream)
