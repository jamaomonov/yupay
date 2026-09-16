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

## Region-split brands

Mobile Legends and Magic Chess: Go Go are sold as two brands each — the
global game and the Russian-region game — because the two are different
supplier games with different player-id spaces. Each brand page links to
its twin («Аккаунт российского региона? Вам на страницу Mobile Legends
RU»), and a not-found verdict on either points at the other. The pairing
is the slug convention `<slug>` ↔ `<slug>-ru`.

## Surfaces

|                | Web (`PurchasePanel`)                             | Mini App (`DynamicFields`)      | Reseller API                                           |
| -------------- | ------------------------------------------------- | ------------------------------- | ------------------------------------------------------ |
| Trigger        | «Проверить» beside the id field, before a package | «Проверить» beside the id field | `POST /merchant/v1/validate/player {brand, player_id}` |
| Verdict scope  | brand slug + id + server                          | brand slug + id + server        | per request; `unsupported` when the brand has no check |
| Blocks Pay     | `invalid` only                                    | `invalid` only                  | never — advisory to the integrator                     |
| Sibling region | link on the page + hint under a not-found verdict | —                               | —                                                      |

See `docs/api/README.md` § `POST /merchant/v1/validate/player` for the
reseller contract and `docs/runbooks/merchant-b2b.md` for the "keeps
answering `error`" runbook.
