import { PIN_CAP } from "./form";
import { T } from "./types";

interface Props {
  checked: boolean;
  otherPins: number;
  onChange: (next: boolean) => void;
}

export function PinField({ checked, otherPins, onChange }: Props) {
  const blocked = checked && otherPins >= PIN_CAP;
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => {
            onChange(e.target.checked);
          }}
        />
        {T.form.pin}
      </label>
      <p className="text-xs text-[var(--text-secondary)]">
        {T.form.pinCount.replace("{used}", String(otherPins)).replace("{cap}", String(PIN_CAP))}
      </p>
      {blocked ? <p className="text-xs text-[var(--danger)]">{T.form.pinCap}</p> : null}
    </div>
  );
}
