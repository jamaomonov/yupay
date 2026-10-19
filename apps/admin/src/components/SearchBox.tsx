import { Input } from "@yupay/ui";
import { Search } from "lucide-react";

interface SearchBoxProps {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  className?: string;
}

/** The admin's search field: an input with a magnifier, same look as the SKU list's. */
export function SearchBox({
  value,
  onChange,
  placeholder,
  className = "min-w-64 flex-1",
}: SearchBoxProps) {
  return (
    <div className={`relative ${className}`}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-secondary)]" />
      <Input
        type="search"
        aria-label={placeholder}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        placeholder={placeholder}
        className="pl-9"
      />
    </div>
  );
}
