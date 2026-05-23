/** Visual editor for `Product.required_fields`.
 *
 * Renders a list of field rows; each row has its own collapsed/expanded view with
 * key/label-per-locale/type/required/pattern/placeholder/options edited inline. The
 * resulting array is form-state under the parent's `required_fields` name.
 */

import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import {
  type Control,
  type UseFormRegister,
  useFieldArray,
  useWatch,
} from "react-hook-form";

import { Button, Input } from "@yupay/ui";

import type { FieldType, FormField } from "../types";

interface Props {
  control: Control<any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
  register: UseFormRegister<any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
  name: string;
}

const FIELD_TYPES: FieldType[] = ["text", "email", "number", "select"];
const LOCALES = ["ru", "en", "uz"] as const;

export function RequiredFieldsEditor({ control, register, name }: Props) {
  const { fields, append, remove } = useFieldArray({ control, name });

  return (
    <div className="space-y-2">
      {fields.map((field, idx) => (
        <FieldRow
          key={field.id}
          index={idx}
          name={name}
          control={control}
          register={register}
          onRemove={() => remove(idx)}
        />
      ))}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() =>
          append({
            key: "",
            label: { ru: "", en: "", uz: "" },
            type: "text",
            required: true,
            placeholder: { ru: "", en: "", uz: "" },
            help_text: { ru: "", en: "", uz: "" },
          } satisfies FormField)
        }
      >
        <Plus className="size-4" />
        Добавить поле
      </Button>
    </div>
  );
}

function FieldRow({
  index,
  name,
  control,
  register,
  onRemove,
}: {
  index: number;
  name: string;
  control: Control<any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
  register: UseFormRegister<any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const path = `${name}.${index.toString()}`;
  const type = useWatch({ control, name: `${path}.type` }) as FieldType | undefined;
  const key = useWatch({ control, name: `${path}.key` }) as string | undefined;

  return (
    <div className="rounded-md border bg-[--bg-surface]">
      <header className="flex items-center justify-between gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 items-center gap-2 text-left text-sm"
        >
          {open ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
          <code className="text-xs">{key || "(новое поле)"}</code>
          <span className="text-xs text-[--text-secondary]">{type ?? ""}</span>
        </button>
        <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
          <Trash2 className="size-4" />
        </Button>
      </header>

      {open && (
        <div className="space-y-3 border-t p-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Labeled label="Key">
              <Input {...register(`${path}.key`)} placeholder="player_id" />
            </Labeled>
            <Labeled label="Type">
              <select
                {...register(`${path}.type`)}
                className="h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
              >
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Labeled>
            <Labeled label="Required">
              <input type="checkbox" {...register(`${path}.required`)} />
            </Labeled>
          </div>

          <div>
            <div className="text-xs font-medium uppercase text-[--text-secondary]">Label</div>
            <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {LOCALES.map((l) => (
                <Input
                  key={l}
                  {...register(`${path}.label.${l}`)}
                  placeholder={l.toUpperCase()}
                />
              ))}
            </div>
          </div>

          <div>
            <div className="text-xs font-medium uppercase text-[--text-secondary]">
              Placeholder
            </div>
            <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {LOCALES.map((l) => (
                <Input
                  key={l}
                  {...register(`${path}.placeholder.${l}`)}
                  placeholder={l.toUpperCase()}
                />
              ))}
            </div>
          </div>

          {/* help_text drives the «Где найти?» bottom-sheet in the miniapp.
              Per-locale because it's user-facing copy: "Profile → Settings →
              copy your numeric ID at the top". Markdown / newlines welcome. */}
          <div>
            <div className="text-xs font-medium uppercase text-[--text-secondary]">
              Help text — «Где найти?»
            </div>
            <p className="mt-1 text-[11px] text-[--text-secondary]">
              Подсказка раскрывается тапом по pill «Где найти?» рядом с полем.
              Если пусто — pill не показывается. Несколько строк допустимо.
            </p>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {LOCALES.map((l) => (
                <textarea
                  key={l}
                  {...register(`${path}.help_text.${l}`)}
                  placeholder={l.toUpperCase()}
                  rows={3}
                  className="min-h-[72px] w-full resize-y rounded-md border border-[--border-default] bg-[--bg-surface] px-3 py-2 text-sm leading-snug"
                />
              ))}
            </div>
          </div>

          <Labeled label="Regex pattern">
            <Input {...register(`${path}.pattern`)} placeholder="^[0-9]{6,15}$" />
          </Labeled>

          {type === "select" && <OptionsEditor name={`${path}.options`} control={control} register={register} />}
        </div>
      )}
    </div>
  );
}

function OptionsEditor({
  name,
  control,
  register,
}: {
  name: string;
  control: Control<any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
  register: UseFormRegister<any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
}) {
  const { fields, append, remove } = useFieldArray({ control, name });
  return (
    <div className="rounded-md border bg-[--bg-muted]/40 p-3">
      <div className="mb-2 text-xs font-medium uppercase text-[--text-secondary]">
        Options
      </div>
      {fields.map((f, idx) => (
        <div key={f.id} className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-5">
          <Input
            {...register(`${name}.${idx.toString()}.value`)}
            placeholder="value"
            className="sm:col-span-1"
          />
          {LOCALES.map((l) => (
            <Input
              key={l}
              {...register(`${name}.${idx.toString()}.label.${l}`)}
              placeholder={l.toUpperCase()}
            />
          ))}
          <Button type="button" variant="ghost" size="sm" onClick={() => remove(idx)}>
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() =>
          append({ value: "", label: { ru: "", en: "", uz: "" } })
        }
      >
        <Plus className="size-4" />
        Опция
      </Button>
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase text-[--text-secondary]">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
