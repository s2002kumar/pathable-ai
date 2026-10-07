import type { CSSProperties } from 'react';
import { cx } from '@/lib/cx';

/**
 * The Golden Master's glyphs, at the sizes the frames draw them.
 *
 * The files in `public/icons` are the Figma exports, unedited. They are used
 * as masks rather than images so a state can recolour one — a selected
 * profile turns emerald — without a second copy of every file; the shape is
 * the asset's own, the colour is `currentColor`.
 */
const ICONS = {
  accessible: [14, 20],
  'add-location': [19, 22],
  'arrow-down': [16, 16],
  'arrow-forward': [13.3333, 13.3333],
  'arrow-outward': [13, 13],
  'arrow-right': [12, 12],
  'arrow-right-small': [14.6667, 14.6667],
  block: [20, 20],
  book: [22, 16],
  brand: [16, 19.5],
  cancel: [20, 20],
  'cancel-circle': [15, 15],
  check: [16.3, 12.025],
  'check-circle': [20, 20],
  'check-circle-outline': [16.6667, 16.6667],
  dash: [13.3333, 3.66667],
  dataset: [15, 15],
  'double-check': [21.9, 12.025],
  elevation: [22, 12],
  eye: [22, 15],
  'fact-check': [16.6667, 15],
  fork: [18, 20],
  help: [16.6667, 16.6667],
  info: [20, 20],
  'info-small': [15, 15],
  layers: [18, 19.05],
  minus: [14, 2],
  navigate: [18, 18],
  'pin-check': [16.3, 12.025],
  'pin-check-small': [13.425, 10.2375],
  'pin-location': [16, 20],
  'pin-question': [20, 20],
  'pin-small': [8.16667, 11.6667],
  'pin-stairs': [18, 18],
  'planner-route': [14, 20],
  plus: [14, 14],
  'profile-cane': [14, 21.5],
  'profile-cane-large': [17.5, 21.55],
  'profile-stroller': [18, 19],
  'profile-walking': [13, 21.5],
  'profile-wheelchair': [16, 19.5],
  'profile-wheelchair-solid': [14, 20],
  question: [20, 20],
  route: [18, 18],
  rule: [18.3333, 14.7354],
  ruler: [16.6667, 12],
  science: [15.0475, 17],
  search: [18, 18],
  shield: [12, 15],
  'shield-check': [16, 22],
  stack: [18, 19.05],
  stairs: [18, 18],
  'surface-pattern': [12.0167, 12],
  swap: [16, 20],
  target: [21.9, 21.9],
  terrain: [18.3333, 15],
  'trending-up': [20, 12],
  tune: [18, 18],
  'tune-small': [15, 15],
  verified: [18.3333, 19.5],
  warning: [22, 19],
  'why-different': [20, 19],
} as const satisfies Record<string, readonly [number, number]>;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  className,
  size,
}: {
  readonly name: IconName;
  readonly className?: string | undefined;
  /** Overrides the frame's own size, keeping the aspect ratio. */
  readonly size?: number;
}) {
  const [width, height] = ICONS[name];
  const scale = size === undefined ? 1 : size / Math.max(width, height);
  const style: CSSProperties = {
    width: `${width * scale}px`,
    height: `${height * scale}px`,
    maskImage: `url(/icons/${name}.svg)`,
    WebkitMaskImage: `url(/icons/${name}.svg)`,
  };
  return <span className={cx('icon', className)} style={style} aria-hidden="true" />;
}
