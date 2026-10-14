/**
 * The brand mark: three concentric rings, a faint sweep and one amber blip. Decorative (the
 * product name is always next to it), so it is hidden from assistive technology.
 */
export function BrandMark({ size = 40 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 48 48"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="24" cy="24" r="21" className="ring ring-outer" />
      <circle cx="24" cy="24" r="14" className="ring ring-mid" />
      <circle cx="24" cy="24" r="7" className="ring ring-inner" />
      <path d="M24 24 L24 3 A21 21 0 0 1 42.2 13.5 Z" className="sweep" />
      <line x1="24" y1="24" x2="24" y2="3" className="beam" />
      <circle cx="32" cy="12.5" r="2.6" className="blip" />
    </svg>
  );
}
