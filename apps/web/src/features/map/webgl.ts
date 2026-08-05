/**
 * WebGL capability detection.
 *
 * MapLibre GL requires WebGL 2. Machines without it are not rare in this product's
 * audience — locked-down institutional laptops, older assistive-tech setups and
 * remote-desktop sessions frequently disable hardware acceleration — so the
 * failure gets a real explanation rather than a blank grey rectangle.
 */

export type WebGlSupport =
  | { readonly supported: true }
  | { readonly supported: false; readonly reason: string };

const NO_CONTEXT_REASON =
  'This browser could not create a WebGL 2 drawing surface. Hardware acceleration ' +
  'may be disabled, or the browser may be too old to display the map.';

const THREW_REASON =
  'This browser blocked the WebGL 2 drawing surface the map needs. Hardware ' +
  'acceleration may be disabled in the browser settings.';

export function detectWebGl(documentRef: Document = document): WebGlSupport {
  try {
    const canvas = documentRef.createElement('canvas');
    const context = canvas.getContext('webgl2');
    if (context === null) {
      return { supported: false, reason: NO_CONTEXT_REASON };
    }
    // Release the probe context immediately; browsers cap simultaneous contexts
    // and MapLibre needs one of its own moments later.
    context.getExtension('WEBGL_lose_context')?.loseContext();
    return { supported: true };
  } catch {
    return { supported: false, reason: THREW_REASON };
  }
}
