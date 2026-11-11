import messages from "@yupay/i18n/locales/ru/merchant.json";
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TopUpMethods } from "./TopUpMethods";

describe("TopUpMethods", () => {
  it("offers the Uzcard / Humo card transfer with both logos", () => {
    const html = renderToStaticMarkup(
      <NextIntlClientProvider
        locale="ru"
        timeZone="Asia/Tashkent"
        messages={{ merchant: messages }}
      >
        <TopUpMethods card usdt={false} usdtNetworks={[]} onPick={() => undefined} />
      </NextIntlClientProvider>,
    );

    expect(html).toContain("Способ пополнения");
    expect(html).toContain("Uzcard / Humo");
    // next/image rewrites src through its loader, so assert the asset and the alt.
    expect(html).toContain("uzcard.png");
    expect(html).toContain("humo.png");
    expect(html).toContain('alt="Uzcard"');
    expect(html).toContain('alt="Humo"');
    expect(html).not.toContain("USDT");
  });

  it("offers USDT alone when the card method is off", () => {
    const html = renderToStaticMarkup(
      <NextIntlClientProvider
        locale="ru"
        timeZone="Asia/Tashkent"
        messages={{ merchant: messages }}
      >
        <TopUpMethods
          card={false}
          usdt
          usdtNetworks={["trc20", "bep20", "erc20"]}
          onPick={() => undefined}
        />
      </NextIntlClientProvider>,
    );

    expect(html).toContain("USDT");
    expect(html).toContain("TRC20 · BEP20 · ERC20");
    expect(html).not.toContain("Uzcard / Humo");
  });
});
