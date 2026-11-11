/**
 * `/payments/usdt` — USDT switch panel, one card per chain (TRC20 / BEP20 /
 * ERC20), then the journal and reservations tabs (ADR-0104).
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchSettings, T, usdtErrorMessage } from "./api";
import { UsdtJournal } from "./UsdtJournal";
import { UsdtNetworkCard } from "./UsdtNetworkCard";
import { UsdtReservations } from "./UsdtReservations";
import { UsdtSettingsPanel } from "./UsdtSettingsPanel";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Spinner } from "@/components/States";
import { Tabs } from "@/components/Tabs";
import { qk } from "@/lib/queryKeys";

type Tab = "journal" | "reservations";

export function UsdtPage() {
  const [tab, setTab] = useState<Tab>("journal");
  const settings = useQuery({ queryKey: qk.usdtSettings(), queryFn: fetchSettings });

  return (
    <div>
      <PageHeader title={T.title} description={T.description} />
      {settings.isLoading ? <Spinner label={T.loading} /> : null}
      {settings.isError ? (
        <ErrorState
          description={usdtErrorMessage(settings.error)}
          onRetry={() => void settings.refetch()}
        />
      ) : null}
      {settings.data ? (
        <>
          <UsdtSettingsPanel settings={settings.data} />
          <h2 className="mb-3 font-medium">{T.networks.title}</h2>
          <div className="mb-6 grid max-w-5xl gap-4 lg:grid-cols-3">
            {settings.data.networks.map((n) => (
              <UsdtNetworkCard key={n.network} network={n} />
            ))}
          </div>
        </>
      ) : null}
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        ariaLabel={T.tabs.aria}
        className="mb-4"
        tabs={[
          { id: "journal", label: T.tabs.journal },
          { id: "reservations", label: T.tabs.reservations },
        ]}
      />
      {tab === "journal" ? <UsdtJournal /> : <UsdtReservations />}
    </div>
  );
}
