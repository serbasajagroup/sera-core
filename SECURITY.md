# Security Policy

sera-core is a safety boundary, so approval bypasses are treated as the highest severity.

## Reporting a vulnerability

Please report privately through GitHub's **"Report a vulnerability"** button (Security tab) or by email to serbasajagroup@gmail.com. Do not open a public issue for a vulnerability.

Please include the affected version, a minimal reproduction, and the impact. We aim to acknowledge reports within 3 business days.

## In scope

- Approving an action without an explicit human decision
- A session grant matching a different chat, action or target than the one approved
- A decision accepted from a non-allowlisted sender or a different chat
- Stale decisions applied after an engine reconnect
- Secrets shown unredacted in public views
- Path traversal or unsafe file names in the WhatsApp helpers

## Supported versions

Only the latest release receives fixes during the 0.x series.
