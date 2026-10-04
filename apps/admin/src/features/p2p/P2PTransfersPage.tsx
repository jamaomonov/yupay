/** `/payments/transfers` — incoming-transfers journal and reservations tabs. */

import { useState } from "react";

import { T } from "./api";
import { P2PJournal } from "./P2PJournal";
import { P2PReservations } from "./P2PReservations";

import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";

type Tab = "journal" | "reservations";

export function P2PTransfersPage() {
  const [tab, setTab] = useState<Tab>("journal");
  return (
    <div>
      <PageHeader title={T.transfers.title} description={T.transfers.description} />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        ariaLabel={T.transfers.tabs.aria}
        className="mb-4"
        tabs={[
          { id: "journal", label: T.transfers.tabs.journal },
          { id: "reservations", label: T.transfers.tabs.reservations },
        ]}
      />
      {tab === "journal" ? <P2PJournal /> : <P2PReservations />}
    </div>
  );
}
