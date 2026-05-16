# Onboarding for AI agents (deeper)

This is the long-form companion to **`AGENTS.md`**. Read `AGENTS.md` first.

## Mental model

Treat YuPay as **eight cooperating but independent businesses**: auth, catalog, inventory,
payments, fulfillment, wallet, promotions, notifications. They live in one repo and one
process today, but every change you make should preserve their ability to be split apart
tomorrow.

When you are tempted to reach across a module boundary (e.g. directly read
`payments.models.Payment` from inside `orders`), **stop**. Either:

- Call the other module's `api.py`, or
- Emit a domain event and have the other module react.

## Doing work

1. **Understand intent**. Read the issue, the spec in `docs/product/flows/`, and any
   relevant ADR. If intent is ambiguous, ask — don't guess.
2. **Plan the change**. For non-trivial work, write the plan into the PR description before
   coding.
3. **TDD when reasonable**. Especially for: domain logic, FSM transitions, money math,
   supplier adapters.
4. **Document as you go**. Architecture and decision changes go into `docs/` in the same PR.
   ADRs first, code second.
5. **Run `make lint typecheck test`** before opening the PR.

## Discipline checks

Before submitting, mentally verify:

- [ ] No business logic in routers.
- [ ] No sync HTTP calls in request handlers.
- [ ] All money in `Decimal` / minor units.
- [ ] All user-facing strings are translation keys, present in all 3 locales.
- [ ] All write endpoints accept `Idempotency-Key`.
- [ ] All webhook bodies are signature-verified **before** parsing.
- [ ] No `Any` / `as` casts without a comment.
- [ ] No new TODOs without a tracked issue link.

## When you don't know

Ask. Or read the source of the module you're touching. Or read the relevant ADR. **Never**
invent a contract or a business rule. **Never** "be helpful" by adding code beyond what the
task asks (see "scope discipline" below).

## Scope discipline

- Don't refactor unrelated files in a feature PR. File a follow-up issue.
- Don't add "future-proofing" — speculative generality is its own form of debt.
- Three similar lines is better than a premature abstraction.
- Don't add error handling for cases that can't happen given internal guarantees.

## Anti-patterns we will reject in review

- Catching `Exception` and logging it without re-raising or handling.
- Sync `requests.get(...)` inside an async function.
- `// @ts-ignore` or `# type: ignore` without an explanatory comment AND a tracked issue.
- New SQL using string interpolation. Always parameters.
- Hardcoded user-facing strings.
- Adding a column without an index for the queries that filter on it.
- Mutating ledger postings or wallet balances directly.

## Asking for help

Open a draft PR with the question in the description. We'd rather review three drafts than
debug one wrong-shape merged feature.
