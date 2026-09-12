import { Input } from "@yupay/ui";

import { eventPhase, fromDatetimeLocal, toDatetimeLocal } from "./form";
import { T } from "./types";

import { Field } from "@/components/Field";

interface Props {
  start: string;
  end: string;
  onStart: (iso: string) => void;
  onEnd: (iso: string) => void;
}

const PHASE_LABEL = {
  live: () => T.form.eventLive,
  upcoming: () => T.form.eventUpcoming,
  ended: () => T.form.eventEnded,
} as const;

export function EventWindowFields({ start, end, onStart, onEnd }: Props) {
  const phase = eventPhase(start, end);
  const chip =
    phase === "live" || phase === "upcoming" || phase === "ended" ? PHASE_LABEL[phase]() : null;

  return (
    <>
      <Field
        label={T.form.eventStart}
        hint={T.form.eventHint}
        error={phase === "invalid" ? T.form.eventNeedWindow : undefined}
      >
        {({ inputProps }) => (
          <Input
            {...inputProps}
            type="datetime-local"
            value={toDatetimeLocal(start)}
            onChange={(e) => {
              onStart(fromDatetimeLocal(e.target.value));
            }}
          />
        )}
      </Field>
      <Field label={T.form.eventEnd}>
        {({ inputProps }) => (
          <Input
            {...inputProps}
            type="datetime-local"
            value={toDatetimeLocal(end)}
            onChange={(e) => {
              onEnd(fromDatetimeLocal(e.target.value));
            }}
          />
        )}
      </Field>
      {chip !== null ? (
        <p className="text-sm text-[var(--text-secondary)] md:col-span-2">{chip}</p>
      ) : null}
    </>
  );
}
