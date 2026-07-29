// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { ArtifactReceipt } from "./ArtifactReceipt";

import type { ReactNode } from "react";

const messages = {
  web: {
    orders: {
      copy: "Copy",
      copied: "Copied",
      walletCredited: "Wallet balance topped up",
      receiptTitle: "Your delivery",
      receipt: {
        code: "Code",
        codes: "Codes",
        key: "Key",
        pin: "PIN",
        serial: "Serial",
        steam_login: "Steam login",
        login: "Login",
        message: "Message",
        note: "Note",
        fulfillment_data: "Your details",
        deliveredNote: "Order delivered.",
      },
    },
  },
};

function wrap(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

it("renders a copyable code with the receipt heading", () => {
  wrap(<ArtifactReceipt artifact={{ code: "ABC-123-XYZ" }} />);
  expect(screen.getByText("Your delivery")).toBeInTheDocument();
  expect(screen.getByText("Code")).toBeInTheDocument();
  expect(screen.getByText("ABC-123-XYZ")).toBeInTheDocument();
});

// Regression: a G2B game top-up delivers `_game_artifact(message=None)` —
// after the Phase 1 whitelist, `message` is the only surviving key and it's
// `null`, which renders nothing. The card must show a human confirmation
// line, not an empty bordered shell.
it("shows the delivered note instead of an empty card when the only key is a null message", () => {
  wrap(<ArtifactReceipt artifact={{ message: null }} />);
  expect(screen.getByText("Order delivered.")).toBeInTheDocument();
  expect(screen.queryByText("Message")).not.toBeInTheDocument();
  expect(screen.queryByText("Your delivery")).not.toBeInTheDocument();
});

// Regression: an artifact whose only surviving whitelisted key is an empty
// `fulfillment_data: {}` must not render an empty card either.
it("shows the delivered note instead of an empty card when fulfillment_data is empty", () => {
  wrap(<ArtifactReceipt artifact={{ fulfillment_data: {} }} />);
  expect(screen.getByText("Order delivered.")).toBeInTheDocument();
  expect(screen.queryByText("Your details")).not.toBeInTheDocument();
});

it("shows the delivered note when the artifact has no whitelisted keys at all", () => {
  wrap(<ArtifactReceipt artifact={{}} />);
  expect(screen.getByText("Order delivered.")).toBeInTheDocument();
});

it("still renders a real message alongside the heading when one is present", () => {
  wrap(<ArtifactReceipt artifact={{ message: "Топ-ап зачислен на ваш аккаунт." }} />);
  expect(screen.getByText("Your delivery")).toBeInTheDocument();
  expect(screen.getByText("Message")).toBeInTheDocument();
  expect(screen.getByText("Топ-ап зачислен на ваш аккаунт.")).toBeInTheDocument();
});
