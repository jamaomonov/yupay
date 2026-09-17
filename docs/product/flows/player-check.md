# Player-id check before paying

The customer types the id an in-game top-up credits (player id, and for
some games a server id) and can ask us to look the account up before
paying. The lookup is advisory — it answers a nickname or "not found", and
never invents a verdict when the supplier is down (ADR-0031). It is
scoped to the **brand**, because a brand is exactly one supplier game
(ADR-0079): every package of the brand credits the same account, so the
check needs no package chosen and survives a package switch.

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant S as Web / Mini App
    participant API as FastAPI
    participant R as Redis
    participant G as G2B / Waxpeer
    participant N as NOVA (ADR-0081)

    C->>S: player id (+ server id), «Проверить»
    S->>API: POST /catalog/brands/{slug}/check-player {player_id, server_id}
    API->>API: brand → one game code (two codes → status=error, no call)
    API->>R: GET playercheck:g2b:{game}:{server}:{hash(id)}
    alt cached valid
        R-->>API: name
    else
        API->>G: checkPlayerId(game, id, server) (short timeout, breaker)
        G-->>API: valid + name | invalid | fault
        API->>R: SET only when valid
        opt G2B/Waxpeer answered error (fault, rate-limit, no mapping, unconfigured…)
            API->>R: GET playercheck:nova:{...}:{hash(id)}
            alt cached valid
                R-->>API: name
            else brand in NOVA_VALIDATE and breaker closed
                API->>N: validate-id / check-login (4s timeout, own breaker)
                N-->>API: valid + name | negative | fault
                API->>R: SET playercheck:nova:* only when valid
            end
        end
    end
    API-->>S: {status: valid|invalid|error, name}
    alt valid
        S->>C: green pill with the nickname; Pay enabled
    else invalid
        S->>C: «Игрок с таким ID не найден»; Pay blocked until the id changes
        S->>C: on a region-split brand: «проверьте на странице <sibling>» link
    else error
        S->>C: «не удалось проверить»; Pay stays enabled
    end
```

Only `invalid` blocks Pay. `error` means our side or the supplier failed and
the customer is not made to pay for it with a blocked button.

**NOVA has no `invalid` edge into this diagram.** It runs only inside the
`error` branch — after the primary has already failed, not instead of it —
and from there it can turn that `error` into `valid`, never into `invalid`.
A NOVA "not found" answer, a brand outside `NOVA_VALIDATE` (five of our
games; global Mobile Legends is deliberately not one of them), or the
breaker being open all fall back to the same `error` the primary would have
produced on its own. The reason is ADR-0031, not a NOVA quirk: `invalid` is
the one verdict that blocks Pay, so it may only come from a check we have
validated against our own brand namespaces — and NOVA, added as a second
opinion for an outage, has not earned that.

## Region-split brands

Mobile Legends and Magic Chess: Go Go are sold as two brands each — the
global game and the Russian-region game — because the two are different
supplier games with different player-id spaces. Each brand page links to
its twin («Аккаунт российского региона? Вам на страницу Mobile Legends
RU»), and a not-found verdict on either points at the other. The pairing
is the slug convention `<slug>` ↔ `<slug>-ru`.

## Surfaces

|                | Web (`PurchasePanel`)                             | Mini App (`DynamicFields`)                           | Reseller API                                           |
| -------------- | ------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------ |
| Trigger        | «Проверить» beside the id field, before a package | «Проверить» beside the id field                      | `POST /merchant/v1/validate/player {brand, player_id}` |
| Verdict scope  | brand slug + id + server                          | brand slug + id + server                             | per request; `unsupported` when the brand has no check |
| Blocks Pay     | `invalid` only                                    | `invalid` only                                       | never — advisory to the integrator                     |
| Sibling region | link on the page + hint under a not-found verdict | region picker on the top-up page (one card per game) | —                                                      |

See `docs/api/README.md` § `POST /merchant/v1/validate/player` for the
reseller contract and `docs/runbooks/merchant-b2b.md` for the "keeps
answering `error`" runbook.
