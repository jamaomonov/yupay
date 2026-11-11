interface TetherMarkProps {
  size?: number;
  className?: string;
}

/** A Tether-style "₮" disc, drawn inline — no image asset to load. */
export function TetherMark({ size = 32, className }: TetherMarkProps) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      focusable="false"
    >
      <circle cx="16" cy="16" r="16" fill="#26A17B" />
      <rect x="8.5" y="7.5" width="15" height="3.6" rx="0.4" fill="#fff" />
      <rect x="14.1" y="7.5" width="3.8" height="17" rx="0.4" fill="#fff" />
      <ellipse cx="16" cy="15.4" rx="8.6" ry="2.3" fill="none" stroke="#fff" strokeWidth="1.7" />
    </svg>
  );
}
