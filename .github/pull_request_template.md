# Summary

<!-- What changes and why. Link the task card or issue. -->

## Type of change

- [ ] Feature
- [ ] Fix
- [ ] Refactor (no behaviour change)
- [ ] Documentation
- [ ] Build, CI or tooling

## Verification

<!-- Paste the commands you actually ran and what they printed. "CI will catch
     it" is not verification. -->

```
pnpm check
uv --directory services/api run pytest
```

- [ ] `pnpm format:check`, `pnpm lint`, `pnpm typecheck` pass
- [ ] `pnpm test` passes
- [ ] `pnpm build` passes
- [ ] `pnpm contracts:check` passes (or contracts were regenerated and committed)
- [ ] Backend integration tests pass against PostGIS, if the database changed
- [ ] `pnpm test:e2e` passes, if the frontend changed

## Accessibility

<!-- Delete if this PR touches no user-facing surface. -->

- [ ] Keyboard reachable, with a visible focus indicator
- [ ] Meaningful accessible names on new interactive or landmark elements
- [ ] Colour is not the only way information is conveyed
- [ ] Contrast meets WCAG AA in both light and dark themes
- [ ] Checked at a narrow viewport; no horizontal overflow
- [ ] axe scan reports no serious or critical violations

> Automated checks catch only a minority of accessibility problems. Say what you
> checked manually.

## Honesty check

PathAble is a product people may one day rely on to move around a city safely.

- [ ] No UI implies a capability that does not exist
- [ ] No accessibility claim is made that the data cannot support
- [ ] Any metric quoted was measured, not estimated
- [ ] The Phase 0 development disclosure is still accurate

## Security and privacy

- [ ] No secrets, tokens or credentials added (including in `NEXT_PUBLIC_*`)
- [ ] `.env.example` updated with placeholders if new configuration was added
- [ ] No new personal data collected or logged
- [ ] Error responses reveal no internals

## Notes for the reviewer

<!-- Trade-offs, deliberate omissions, follow-up work. Anything you are unsure
     about is worth naming here rather than hoping it is not noticed. -->
