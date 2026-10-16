import { describe, expect, it } from 'vitest';
import { metadata } from './layout';

describe('site metadata', () => {
  const description = String(metadata.description);

  it('describes what is actually running, and no more', () => {
    expect(description).toContain('public pilot for Waterloo, Ontario');
    expect(description).toContain('it advises, it does not certify');
    // Stale since the pilot went public, or claims the claims ledger prohibits.
    expect(description).not.toMatch(/local|engineering build|not deployed/i);
    expect(description).not.toMatch(/launched|production|certified accessible|\bAI\b/i);
  });

  it('still asks search engines not to index an uncertified pilot', () => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });
});
