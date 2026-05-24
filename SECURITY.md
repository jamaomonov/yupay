# Security Policy

## Reporting a Vulnerability

If you believe you have found a security vulnerability in YuPay, please **do not** open a public
issue. Instead, email the security team at `security@yupay.io` with:

- A description of the issue
- Steps to reproduce
- The potential impact
- (Optional) A suggested fix

We will acknowledge receipt within 48 hours and provide a status update within 7 days.

## Supported Versions

Only the latest `main` branch and the most recent tagged release receive security updates.

## Scope

In scope:

- Authentication and authorization flaws
- Payment processing vulnerabilities
- Data exposure (PII, tokens, secrets)
- Injection (SQL, command, template)
- SSRF, RCE, XXE
- Insecure deserialization
- Webhook signature bypass

Out of scope:

- Best-practice suggestions without an exploit
- Issues in third-party services we depend on (report to the vendor)
- Social engineering

## Disclosure Policy

We follow coordinated disclosure. After a fix is deployed, we will publish a security advisory
describing the issue and credit the reporter (unless they prefer to remain anonymous).
