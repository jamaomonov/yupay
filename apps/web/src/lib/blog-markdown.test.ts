import { expect, test, vi } from "vitest";

vi.mock("./blog", () => ({
  listPublishedPosts: () =>
    Promise.resolve({
      items: [
        {
          slug: "kak-popolnit",
          title: "Как пополнить MLBB",
          excerpt: "По ID, без пароля.",
        },
      ],
      next_cursor: null,
    }),
  getPublishedPost: (slug: string) =>
    Promise.resolve(
      slug === "kak-popolnit"
        ? {
            slug: "kak-popolnit",
            title: "Как пополнить MLBB",
            excerpt: "По ID, без пароля.",
            cover_image_url: "https://cdn.yupay.uz/blog/x.webp",
            body_html:
              "<h2>Перед покупкой</h2><p>Нужен <strong>ID</strong> и <a href=\"/store/mobile-legends\">карточка</a>.</p>" +
              "<ol><li>Откройте игру</li><li>Оплатите</li></ol>" +
              "<pre><code>POST /check</code></pre>",
            faqs: [{ question: "Нужен пароль?", answer: "Нет." }],
            show_buy_card: true,
            primary_brand: { slug: "mobile-legends", name: "Mobile Legends" },
          }
        : null,
    ),
}));

import { blogIndexMarkdown, blogPostMarkdown, htmlToMarkdown } from "./blog-markdown";

test("htmlToMarkdown keeps headings, links, lists and fences", () => {
  const md = htmlToMarkdown(
    "<h2>Шаг</h2><p>Нужен <strong>ID</strong> на <a href=\"/store/mlbb\">странице</a>.</p>" +
      "<ul><li>Один</li><li>Два</li></ul>" +
      "<blockquote><p>Цены в тексте не пишем.</p></blockquote>" +
      "<pre><code>echo 1</code></pre>",
  );
  expect(md).toContain("## Шаг");
  expect(md).toContain("**ID**");
  expect(md).toContain("[странице](https://yupay.uz/store/mlbb)");
  expect(md).toContain("- Один");
  expect(md).toContain("> Цены в тексте не пишем.");
  expect(md).toContain("```\necho 1\n```");
});

test("htmlToMarkdown renders a table", () => {
  const md = htmlToMarkdown(
    "<table><thead><tr><th>Регион</th><th>Оплата</th></tr></thead>" +
      "<tbody><tr><td>Узбекистан</td><td>Click</td></tr></tbody></table>",
  );
  expect(md).toContain("| Регион | Оплата |");
  expect(md).toContain("| --- | --- |");
  expect(md).toContain("| Узбекистан | Click |");
});

test("blog index lists published posts as absolute links", async () => {
  const out = await blogIndexMarkdown("ru");
  expect(out).toContain("# Блог YuPay");
  expect(out).toContain("[Как пополнить MLBB](https://yupay.uz/blog/kak-popolnit): По ID, без пароля.");
});

test("blog post markdown 404s a missing slug and renders a known one", async () => {
  await expect(blogPostMarkdown("ru", "net")).resolves.toBeNull();
  const out = await blogPostMarkdown("ru", "kak-popolnit");
  expect(out).not.toBeNull();
  expect(out).toContain("# Как пополнить MLBB");
  expect(out).toContain("## Перед покупкой");
  expect(out).toContain("[карточка](https://yupay.uz/store/mobile-legends)");
  expect(out).toContain("### Нужен пароль?");
  expect(out).toContain("[Пополнить Mobile Legends](https://yupay.uz/store/mobile-legends)");
  expect(out).toContain("[Статья на сайте](https://yupay.uz/blog/kak-popolnit)");
});
