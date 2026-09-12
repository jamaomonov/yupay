# Read a published blog post

A guest opens an editorial URL on the storefront. Prices come from the live
catalogue, not from the article HTML.

```mermaid
sequenceDiagram
    autonumber
    actor R as Reader
    participant Web as apps/web
    participant API as blog.routes
    participant Cat as catalog

    R->>Web: GET /{locale}/blog/{slug}
    Web->>API: GET /blog/{slug} (Accept-Language)
    API-->>Web: published translation + locale_slugs + faqs
    alt show_buy_card
        Web->>Cat: GET /catalog/brands/{slug}
        Cat-->>Web: name, art, starting_display_price
    end
    Web-->>R: article, JSON-LD, live buy card
    R->>Web: like / share (optional, no login)
    Web->>API: POST /blog/{slug}/view then POST|DELETE /blog/{slug}/like
    API-->>Web: liked + counts (yp_blog_reader cookie)
```

Drafts and missing locales are 404. Archive keeps `published_at` so an
indexed URL can still be explained later; v1 does not hard-delete.
