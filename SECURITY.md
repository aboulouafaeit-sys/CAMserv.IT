# Security Policy & Vulnerability Disclosure

## Supported Versions

CAMserv provides continuous security updates and patches for active release tracks:

| Version Track | Supported | Security Patch SLA |
| :--- | :---: | :--- |
| **0.2.x (Current / Active)** | **Yes** | Within 48 hours for Critical / High severity |
| **0.1.x (Legacy Baseline)** | **Yes** | Backported critical security fixes |
| **< 0.1.0** | No | Upgrade to latest release |

---

## Reporting a Security Vulnerability

We take the security of CAMserv and the protection of sovereign video surveillance data seriously. If you discover a security vulnerability, we appreciate your responsible disclosure.

### How to Report
- **Preferred Method:** Open a private security advisory via [GitHub Security Advisories](https://github.com/aboulouafaeit-sys/CAMserv.IT/security/advisories/new).
- **Direct Email:** Send an encrypted email to `security@camserv.local` (or project maintainers) with the subject line `[SECURITY DISCLOSURE] CAMserv Vulnerability Report`.

### What to Include
To help us triage and remediate the issue rapidly, please provide:
1. Description of the vulnerability and potential impact.
2. Exact affected component, file, and line references.
3. Step-by-step reproducible proof-of-concept (PoC) using synthetic/mock data.
4. Any proposed remediation or patch.

---

## Response & Disclosure Process

1. **Acknowledgment:** Our security engineering team will acknowledge receipt of your report within **24 hours**.
2. **Assessment:** We will confirm the vulnerability and assign a CVSS severity score within **48 hours**.
3. **Remediation:** A controlled, non-destructive patch will be developed, accompanied by automated regression tests in an isolated branch.
4. **Coordinated Disclosure:** We will publish a security advisory and release a patched version, crediting the discoverer (unless anonymity is requested).

---

## Safe Harbor & Research Rules

We consider security research conducted in good faith to be authorized. When researching:
- Never execute attacks against physical critical infrastructure or production video surveillance deployments.
- Never access, download, or expose private personal video footage.
- Use isolated local synthetic fixtures and test harnesses (`pytest`).
