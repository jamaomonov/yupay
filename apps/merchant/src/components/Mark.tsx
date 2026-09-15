/**
 * The YuPay mark.
 *
 * One copy. It was pasted into the landing and the cabinet shell, and the two
 * had already drifted apart in colour class — which is how a logo ends up
 * looking almost the same in two places.
 *
 * `aria-hidden`: it always sits beside the wordmark, so announcing it would
 * say the name twice.
 */
export function Mark({ className = "" }: { className?: string }) {
  return (
    <svg
      width="20"
      height="18"
      viewBox="0 0 471.8 426.26"
      aria-hidden="true"
      className={`text-primary-ink ${className}`}
    >
      <path
        fill="currentColor"
        d="M0.06 23.83l0 294.05c0,0 -5.53,87.63 88.85,108.37l230.68 0c0,0 68.19,-17.67 80.63,-88.17l0 -210.84 71.58 0 -57.83 -63.63 -57.83 -63.63 -57.83 63.63 -57.83 63.63 71.57 0 0 183.78c0,0 -5.1,27.06 -30.74,27.06l-167.01 0c0,0 -26.08,-1.43 -26.08,-20.21l0 -294.05 -88.17 0z"
      />
    </svg>
  );
}
