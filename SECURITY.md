# Security Policy

## Supported versions

Security fixes are released for the latest minor version only.

| Version | Supported |
|---------|-----------|
| 0.4.x   | ✅        |
| < 0.4   | ❌        |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public issues,
discussions or pull requests.**

Use GitHub's private vulnerability reporting instead:

1. Open the [Security tab](https://github.com/erelbi/sangfor-scp/security) of this repository.
2. Click **Report a vulnerability** and fill in the form.

Please include:

- the affected version and the component (e.g. `auth/ec2.py`, `client.py`)
- steps to reproduce or a proof of concept
- the impact you expect (credential exposure, request forgery, etc.)

Do not include real credentials, hostnames or other data from your SCP
environment in the report.

You can expect an acknowledgement within 7 days. We will keep you informed
while a fix is prepared and credit you in the release notes unless you prefer
to stay anonymous.

## Scope

In scope: this library's code — request signing (EC2 / AWS4-HMAC-SHA256),
token authentication, credential handling, and the `scp-health` CLI.

Out of scope: vulnerabilities in Sangfor Cloud Platform itself. Report those to
Sangfor directly.

## Using the library safely

- `verify_ssl` defaults to `False` because SCP ships with a self-signed
  certificate. In production, install a trusted certificate on SCP or point
  `requests` at your CA bundle and pass `verify_ssl=True`.
- Keep access keys out of source code and version control — use environment
  variables or a git-ignored `.env` file.
- Create a dedicated SCP access key with the minimum role the task needs; for
  `scp-health` a read-only role is enough.
- Rotate keys that were ever pasted into chats, tickets or logs.
