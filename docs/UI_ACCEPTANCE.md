# Dashboard acceptance checklist — every item must pass BEFORE showing Rayyan anything
Source: his original brief + today's feedback. Verify with a rendered screenshot at desktop (1400px) AND phone (390px), not just tests.
- [ ] First screen: engine health (green/amber/red), data age, uptime, next cycle, "research only / no orders".
- [ ] Live P&L visible immediately: balance, today, week, month, all-time, floating, wins/losses. Real numbers only; empty states say so.
- [ ] ONE card per trade holding: pair, direction, state, P&L (large), chart with entry/stop/target/fill/now, size, risk/reward, reason (2 lines), timeline, UNPROVEN tag.
- [ ] All text readable on a phone without zooming (>= 12px effective; charts drawn at real width, not scaled-down SVG).
- [ ] Charts: all 10 pairs, M15/H1/H4, key levels, sessions, trade overlay, hover values.
- [ ] Research tab: every strategy tested, verdicts, what each does, indicators tested vs not tested.
- [ ] System tab: cycle success, freshness, alert latency, audit text. Nothing invented.
- [ ] Loads instantly (cached page; background rebuild); shows how old the page is.
- [ ] No console errors in the rendered page (playwright check).
