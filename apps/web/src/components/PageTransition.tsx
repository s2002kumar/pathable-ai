import * as React from 'react';
import type { ComponentType, ReactNode, ViewTransitionProps } from 'react';

/** The transition type the landing page's links into the planner carry. */
export const TO_PLANNER = 'to-planner';

const NativeViewTransition = (
  React as unknown as { ViewTransition?: ComponentType<ViewTransitionProps> }
).ViewTransition;

/**
 * React's `<ViewTransition>`, where the running React has it.
 *
 * The App Router ships a React canary that does; the stable React the unit
 * tests run on does not, and there the children render unwrapped — the same
 * page, minus the navigation animation. A browser without the View
 * Transitions API gets that same outcome from React itself, and reduced
 * motion turns the animation off in globals.css.
 */
export function PageTransition({
  children,
  ...props
}: ViewTransitionProps & { readonly children: ReactNode }) {
  if (NativeViewTransition === undefined) return <>{children}</>;
  return <NativeViewTransition {...props}>{children}</NativeViewTransition>;
}
