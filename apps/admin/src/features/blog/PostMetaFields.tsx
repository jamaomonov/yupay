import { Input, Select } from "@yupay/ui";

import { EventWindowFields } from "./EventWindowFields";
import { fromDatetimeLocal, toDatetimeLocal } from "./form";
import { PinField } from "./PinField";
import { KINDS, T, type PostKind } from "./types";

import type { Brand } from "@/features/catalog/types";

import { Field } from "@/components/Field";
import { ImageUploader } from "@/components/ImageUploader";

interface Props {
  kind: PostKind;
  brandId: string;
  cover: string;
  buyCard: boolean;
  pin: boolean;
  otherPins: number;
  eventStart: string;
  eventEnd: string;
  scheduleAt: string;
  canSchedule: boolean;
  brands: Brand[];
  onKind: (kind: PostKind) => void;
  onBrandId: (id: string) => void;
  onCover: (url: string) => void;
  onBuyCard: (next: boolean) => void;
  onPin: (next: boolean) => void;
  onEventStart: (iso: string) => void;
  onEventEnd: (iso: string) => void;
  onScheduleAt: (iso: string) => void;
}

export function PostMetaFields({
  kind,
  brandId,
  cover,
  buyCard,
  pin,
  otherPins,
  eventStart,
  eventEnd,
  scheduleAt,
  canSchedule,
  brands,
  onKind,
  onBrandId,
  onCover,
  onBuyCard,
  onPin,
  onEventStart,
  onEventEnd,
  onScheduleAt,
}: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label={T.form.kind}>
        {({ inputProps }) => (
          <Select
            {...inputProps}
            value={kind}
            onChange={(e) => {
              const next = KINDS.find((k) => k === e.target.value);
              if (next !== undefined) onKind(next);
            }}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {T.kind[k]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={T.form.brand}>
        {({ inputProps }) => (
          <Select
            {...inputProps}
            value={brandId}
            onChange={(e) => {
              onBrandId(e.target.value);
            }}
          >
            <option value="">{T.form.needBrand}</option>
            {brands.map((b) => (
              <option key={b.id} value={b.id}>
                {b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={T.form.cover}>
        {({ inputProps }) => (
          <div id={inputProps.id}>
            <ImageUploader
              value={cover || null}
              onChange={onCover}
              kind="blog_image"
              hint={T.form.coverHint}
            />
          </div>
        )}
      </Field>
      <div className="flex flex-col justify-end gap-3 pb-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={buyCard}
            onChange={(e) => {
              onBuyCard(e.target.checked);
            }}
          />
          {T.form.buyCard}
        </label>
        <PinField checked={pin} otherPins={otherPins} onChange={onPin} />
      </div>
      {kind === "event" ? (
        <EventWindowFields start={eventStart} end={eventEnd} onStart={onEventStart} onEnd={onEventEnd} />
      ) : null}
      {canSchedule ? (
        <Field label={T.form.scheduleAt}>
          {({ inputProps }) => (
            <Input
              {...inputProps}
              type="datetime-local"
              value={toDatetimeLocal(scheduleAt)}
              onChange={(e) => {
                onScheduleAt(fromDatetimeLocal(e.target.value));
              }}
            />
          )}
        </Field>
      ) : null}
    </div>
  );
}
