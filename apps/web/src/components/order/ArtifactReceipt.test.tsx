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

it("renders every code of a multi-code voucher purchase", () => {
  wrap(<ArtifactReceipt artifact={{ code: "A-1", codes: ["A-1", "B-2"] }} />);
  expect(screen.getByText("Codes")).toBeInTheDocument();
  expect(screen.getByText("A-1")).toBeInTheDocument();
  expect(screen.getByText("B-2")).toBeInTheDocument();
  // `code` (=== codes[0]) must not show a duplicate "Code" row alongside "Codes".
  expect(screen.queryByText("Code")).not.toBeInTheDocument();
});

it("shows a redemption note alongside a real key", () => {
  wrap(<ArtifactReceipt artifact={{ key: "STEAM-KEY-1", message: "Redeem in the client." }} />);
  expect(screen.getByText("Your delivery")).toBeInTheDocument();
  expect(screen.getByText("STEAM-KEY-1")).toBeInTheDocument();
  expect(screen.getByText("Message")).toBeInTheDocument();
  expect(screen.getByText("Redeem in the client.")).toBeInTheDocument();
});

// A top-up receipt has NO deliverable — the login is the target account (shown
// in the order composition), never dressed up as "Ваша выдача". The block must
// be absent entirely, not an empty shell or a login masquerading as a delivery.
it("renders nothing for a top-up receipt whose only key is the target login", () => {
  const { container } = wrap(<ArtifactReceipt artifact={{ steam_login: "_jamshid__" }} />);
  expect(container).toBeEmptyDOMElement();
  expect(screen.queryByText("Your delivery")).not.toBeInTheDocument();
  expect(screen.queryByText("_jamshid__")).not.toBeInTheDocument();
});

it("renders nothing when the only key is a null message", () => {
  const { container } = wrap(<ArtifactReceipt artifact={{ message: null }} />);
  expect(container).toBeEmptyDOMElement();
});

it("renders nothing when fulfillment_data is the only (empty) key", () => {
  const { container } = wrap(<ArtifactReceipt artifact={{ fulfillment_data: {} }} />);
  expect(container).toBeEmptyDOMElement();
});

it("renders nothing when the artifact has no whitelisted keys at all", () => {
  const { container } = wrap(<ArtifactReceipt artifact={{}} />);
  expect(container).toBeEmptyDOMElement();
});

it("renders nothing when a message is present without any real deliverable", () => {
  const { container } = wrap(
    <ArtifactReceipt artifact={{ message: "Топ-ап зачислен на ваш аккаунт." }} />,
  );
  expect(container).toBeEmptyDOMElement();
  expect(screen.queryByText("Your delivery")).not.toBeInTheDocument();
});
