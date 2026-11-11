/** `/payments/usdt` — USDT (TRC20) switch panel plus the journal and reservations tabs (ADR-0104). */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchSettings, T, usdtErrorMessage } from "./api";
import { UsdtJournal } from "./UsdtJournal";
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
      {settings.data ? <UsdtSettingsPanel settings={settings.data} /> : null}
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
