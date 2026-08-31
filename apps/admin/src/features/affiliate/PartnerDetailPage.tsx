import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  COMMISSION_RANGE,
  DISCOUNT_RANGE,
  fmtDate,
  type CodeOut,
  type PartnerDetailOut,
  type PartnerOut,
} from "./types";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

const STATUS_LABEL: Record<string, string> = {
  pending: "ожидает",
  active: "активен",
  suspended: "отключён",
  rejected: "отклонён",
};

function fmtMoney(v: string): string {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("ru-RU") : v;
}

/**
 * One partner: profile editing, their codes, rolling stats and balance.
 *
 * Split off the list page so the two admin verbs that used to fail there have
 * room to work: reactivation exists at all (the backend grew `unsuspend`),
 * and code issuing shows the codes that already exist instead of a button
 * that never learns it has been pressed.
 */
export function PartnerDetailPage() {
  const params = useParams<{ id: string }>();
  const partnerId = params.id ?? "";
  const qc = useQueryClient();

  const query = useQuery<PartnerDetailOut>({
    queryKey: ["admin", "affiliate", "partner", partnerId],
    queryFn: () => apiGet<PartnerDetailOut>(`/api/v1/admin/affiliate/partners/${partnerId}`),
    enabled: Boolean(partnerId),
  });

  const invalidate = async (): Promise<void> => {
    await qc.invalidateQueries({ queryKey: ["admin", "affiliate"] });
  };

  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />;
  if (query.isPending || !query.data) return <Spinner label="Загрузка…" />;

  const { partner, codes, stats_month, stats_year, balance } = query.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title={partner.display_name ?? partner.email}
        description={`${partner.email} · ${STATUS_LABEL[partner.status] ?? partner.status} · с нами с ${fmtDate(partner.created_at)}`}
        breadcrumbs={[
          { label: "Партнёры", to: "/affiliate/partners" },
          { label: partner.display_name ?? partner.email },
        ]}
      />
      <StatusActions partner={partner} onDone={invalidate} />
      <div className="grid gap-6 lg:grid-cols-2">
        <ProfileCard partner={partner} onSaved={invalidate} />
        <StatsCard stats_month={stats_month} stats_year={stats_year} balance={balance} />
      </div>
      <CodesCard partnerId={partner.id} codes={codes} onChanged={invalidate} />
    </div>
  );
}

function StatusActions({ partner, onDone }: { partner: PartnerOut; onDone: () => Promise<void> }) {
  const toast = useToast();

  const suspend = useMutation({
    mutationFn: () =>
      apiPost<PartnerOut>(`/api/v1/admin/affiliate/partners/${partner.id}/suspend`, {}),
    onSuccess: async () => {
      toast.success("Партнёр отключён");
      await onDone();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const unsuspend = useMutation({
    mutationFn: () =>
      apiPost<PartnerOut>(`/api/v1/admin/affiliate/partners/${partner.id}/unsuspend`, {}),
    onSuccess: async () => {
      toast.success("Партнёр снова активен");
      await onDone();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const reinvite = useMutation({
    mutationFn: () =>
      apiPost<{ link: string; emailed: boolean }>(
        `/api/v1/admin/affiliate/partners/${partner.id}/reinvite`,
        {},
      ),
    onSuccess: async (res) => {
      await navigator.clipboard.writeText(res.link).catch(() => undefined);
      toast.success(
        res.emailed
          ? "Ссылка отправлена на почту (и скопирована в буфер)"
          : "Письмо не ушло — ссылка скопирована в буфер",
      );
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  function confirmSuspend(): void {
    // Spelled out because "suspend" does not say either half: the code stops
    // working for buyers *and* the partner is signed out of their panel.
    const ok = window.confirm(
      `Отключить ${partner.email}?\n\n` +
        "Его промокод перестанет действовать на кассе, а сам он выйдет из панели. " +
        "Уже начисленная комиссия останется за ним.",
    );
    if (ok) suspend.mutate();
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {partner.status === "suspended" ? (
        <Button
          size="sm"
          onClick={() => {
            unsuspend.mutate();
          }}
          disabled={unsuspend.isPending}
        >
          Активировать
        </Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          onClick={confirmSuspend}
          disabled={partner.status !== "active" || suspend.isPending}
        >
          Отключить
        </Button>
      )}
      {partner.status === "active" && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            reinvite.mutate();
          }}
          disabled={reinvite.isPending}
        >
          Выслать ссылку на пароль
        </Button>
      )}
    </div>
  );
}

function ProfileCard({ partner, onSaved }: { partner: PartnerOut; onSaved: () => Promise<void> }) {
  const toast = useToast();
  const [displayName, setDisplayName] = useState(partner.display_name ?? "");
  const [contact, setContact] = useState(partner.contact ?? "");
  const [channel, setChannel] = useState(partner.channel ?? "");
  const [note, setNote] = useState(partner.admin_note ?? "");

  // A background refetch (after unsuspend etc.) hands back fresh partner
  // props; untouched forms should follow them rather than show stale drafts.
  useEffect(() => {
    setDisplayName(partner.display_name ?? "");
    setContact(partner.contact ?? "");
    setChannel(partner.channel ?? "");
    setNote(partner.admin_note ?? "");
  }, [partner]);

  const save = useMutation({
    mutationFn: () =>
      apiPatch<PartnerOut>(`/api/v1/admin/affiliate/partners/${partner.id}`, {
        display_name: displayName,
        contact,
        channel,
        admin_note: note,
      }),
    onSuccess: async () => {
      toast.success("Сохранено");
      await onSaved();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const dirty =
    displayName !== (partner.display_name ?? "") ||
    contact !== (partner.contact ?? "") ||
    channel !== (partner.channel ?? "") ||
    note !== (partner.admin_note ?? "");

  return (
    <section className="border-default bg-surface space-y-3 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">Данные</h2>
      <label className="block text-xs">
        <span className="text-muted mb-1 block">Имя</span>
        <Input
          value={displayName}
          onChange={(e) => {
            setDisplayName(e.target.value);
          }}
        />
      </label>
      <label className="block text-xs">
        <span className="text-muted mb-1 block">Контакт (Telegram, телефон)</span>
        <Input
          value={contact}
          onChange={(e) => {
            setContact(e.target.value);
          }}
        />
      </label>
      <label className="block text-xs">
        <span className="text-muted mb-1 block">Канал / площадка</span>
        <Input
          value={channel}
          onChange={(e) => {
            setChannel(e.target.value);
          }}
        />
      </label>
      <label className="block text-xs">
        <span className="text-muted mb-1 block">Заметка (видна только админам)</span>
        <Input
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
      </label>
      <Button
        size="sm"
        onClick={() => {
          save.mutate();
        }}
        disabled={!dirty || save.isPending}
      >
        Сохранить
      </Button>
    </section>
  );
}

function StatsCard({
  stats_month,
  stats_year,
  balance,
}: Pick<PartnerDetailOut, "stats_month" | "stats_year" | "balance">) {
  const rows = [
    { label: "30 дней", s: stats_month },
    { label: "365 дней", s: stats_year },
  ];
  return (
    <section className="border-default bg-surface space-y-3 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">Статистика</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted text-left text-xs">
            <th className="py-1 font-normal">Окно</th>
            <th className="py-1 font-normal">Заработано</th>
            <th className="py-1 font-normal">Заказы</th>
            <th className="py-1 font-normal">Активации</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-default border-t">
              <td className="py-1.5">{r.label}</td>
              <td className="py-1.5">{fmtMoney(r.s.earned)} сум</td>
              <td className="py-1.5">{r.s.orders}</td>
              <td className="py-1.5">{r.s.activations}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-muted text-xs">
        Баланс: доступно {fmtMoney(balance.available ?? "0")} · в холде{" "}
        {fmtMoney(balance.held ?? "0")} · в выплате {fmtMoney(balance.reserved ?? "0")}
      </div>
    </section>
  );
}

function CodesCard({
  partnerId,
  codes,
  onChanged,
}: {
  partnerId: string;
  codes: CodeOut[];
  onChanged: () => Promise<void>;
}) {
  const toast = useToast();
  const hasActive = codes.some((c) => c.active);
  const [issuing, setIssuing] = useState(false);
  const [code, setCode] = useState("");
  const [discount, setDiscount] = useState("5");
  const [commission, setCommission] = useState("2");

  const issue = useMutation({
    mutationFn: () =>
      apiPost<CodeOut>(`/api/v1/admin/affiliate/partners/${partnerId}/codes`, {
        code,
        discount_percent: discount,
        commission_percent: commission,
      }),
    onSuccess: async (created) => {
      toast.success(`Код ${created.code} выдан`);
      setIssuing(false);
      setCode("");
      await onChanged();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const toggle = useMutation({
    mutationFn: (c: CodeOut) =>
      apiPatch<CodeOut>(`/api/v1/admin/affiliate/codes/${c.id}`, { active: !c.active }),
    onSuccess: async (updated) => {
      toast.success(
        updated.active ? `Код ${updated.code} включён` : `Код ${updated.code} выключен`,
      );
      await onChanged();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const [editing, setEditing] = useState<string | null>(null);
  const [editDiscount, setEditDiscount] = useState("");
  const [editCommission, setEditCommission] = useState("");

  const retune = useMutation({
    mutationFn: (codeId: string) =>
      apiPatch<CodeOut>(`/api/v1/admin/affiliate/codes/${codeId}`, {
        discount_percent: editDiscount,
        commission_percent: editCommission,
      }),
    onSuccess: async (updated) => {
      // Live at accrual time: the new commission applies to future orders,
      // never retroactively — worth saying at the moment it changes.
      toast.success(`Код ${updated.code} обновлён — проценты действуют на будущие заказы`);
      setEditing(null);
      await onChanged();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const remove = useMutation({
    mutationFn: (codeId: string) => apiDelete(`/api/v1/admin/affiliate/codes/${codeId}`),
    onSuccess: async () => {
      toast.success("Код удалён");
      await onChanged();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  function confirmDelete(c: CodeOut): void {
    const ok = window.confirm(
      `Удалить код ${c.code}?\n\n` +
        "Удалить можно только код, которым ещё не пользовались. " +
        "Использованный код сервер откажется удалять — его нужно выключить.",
    );
    if (ok) remove.mutate(c.id);
  }

  function startEdit(c: CodeOut): void {
    setEditing(c.id);
    setEditDiscount(c.discount_percent);
    setEditCommission(c.commission_percent);
  }

  return (
    <section className="border-default bg-surface space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Промокоды</h2>
        {!issuing && (
          <Button
            size="sm"
            variant={hasActive ? "ghost" : "primary"}
            onClick={() => {
              setIssuing(true);
            }}
          >
            {hasActive ? "Выдать ещё код" : "Выдать код"}
          </Button>
        )}
      </div>
      {codes.length === 0 && !issuing && (
        <p className="text-muted text-sm">Кодов ещё нет — выдайте первый.</p>
      )}
      {codes.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted text-left text-xs">
              <th className="py-1 font-normal">Код</th>
              <th className="py-1 font-normal">Скидка</th>
              <th className="py-1 font-normal">Комиссия</th>
              <th className="py-1 font-normal">Статус</th>
              <th className="py-1 font-normal">Выдан</th>
              <th className="py-1 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {codes.map((c) =>
              editing === c.id ? (
                <tr key={c.id} className="border-default border-t">
                  <td className="py-1.5 font-mono">{c.code}</td>
                  <td className="py-1.5">
                    <Input
                      aria-label={`Скидка ${c.code}`}
                      value={editDiscount}
                      onChange={(e) => {
                        setEditDiscount(e.target.value);
                      }}
                      className="w-20"
                    />
                  </td>
                  <td className="py-1.5">
                    <Input
                      aria-label={`Комиссия ${c.code}`}
                      value={editCommission}
                      onChange={(e) => {
                        setEditCommission(e.target.value);
                      }}
                      className="w-20"
                    />
                  </td>
                  <td className="text-muted py-1.5 text-xs" colSpan={2}>
                    скидка {DISCOUNT_RANGE.min}–{DISCOUNT_RANGE.max}% · комиссия{" "}
                    {COMMISSION_RANGE.min}–{COMMISSION_RANGE.max}% · на будущие заказы
                  </td>
                  <td className="whitespace-nowrap py-1.5 text-right">
                    <Button
                      size="sm"
                      onClick={() => {
                        retune.mutate(c.id);
                      }}
                      disabled={retune.isPending}
                    >
                      Сохранить
                    </Button>{" "}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setEditing(null);
                      }}
                    >
                      Отмена
                    </Button>
                  </td>
                </tr>
              ) : (
                <tr key={c.id} className="border-default border-t">
                  <td className="py-1.5 font-mono">{c.code}</td>
                  <td className="py-1.5">{c.discount_percent}%</td>
                  <td className="py-1.5">{c.commission_percent}%</td>
                  <td className="py-1.5">{c.active ? "действует" : "выключен"}</td>
                  <td className="text-muted py-1.5 text-xs">{fmtDate(c.created_at)}</td>
                  <td className="whitespace-nowrap py-1.5 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        startEdit(c);
                      }}
                    >
                      Изменить
                    </Button>{" "}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        toggle.mutate(c);
                      }}
                      disabled={toggle.isPending}
                    >
                      {c.active ? "Выключить" : "Включить"}
                    </Button>{" "}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        confirmDelete(c);
                      }}
                      disabled={remove.isPending}
                    >
                      Удалить
                    </Button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}
      {issuing && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs">
            <span className="text-muted mb-1 block">Код</span>
            <Input
              value={code}
              onChange={(e) => {
                setCode(e.target.value.toUpperCase());
              }}
              placeholder="PARTNER10"
              className="w-36"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted mb-1 block">
              Скидка {DISCOUNT_RANGE.min}–{DISCOUNT_RANGE.max}%
            </span>
            <Input
              value={discount}
              onChange={(e) => {
                setDiscount(e.target.value);
              }}
              className="w-20"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted mb-1 block">
              Комиссия {COMMISSION_RANGE.min}–{COMMISSION_RANGE.max}%
            </span>
            <Input
              value={commission}
              onChange={(e) => {
                setCommission(e.target.value);
              }}
              className="w-20"
            />
          </label>
          <Button
            size="sm"
            onClick={() => {
              issue.mutate();
            }}
            disabled={issue.isPending || !code.trim()}
          >
            Выдать
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setIssuing(false);
            }}
          >
            Отмена
          </Button>
        </div>
      )}
    </section>
  );
}
