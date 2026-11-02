# Portable native agent workflow

Authorization: November 2, 2026. Read root AGENTS.md and
[current policy](../../tools/devloop/guarded/POLICY.md). Older Muse-first coding
instructions do not block native work on a teammate's machine.

## Implement and check

Use a clean issue branch and a bounded packet naming goal, acceptance criteria,
exact owned source/test paths and required checks. Coordinate shared contracts.
Use native Codex with Sol/Terra selected, or terminal Claude Code explicitly:

```powershell
codex
claude --model sonnet
```

Claude uses the existing subscription login. If rate-limited, checkpoint and let
Codex continue. No Fable/Haiku or paid API-key fallback. Give parallel agents
separate checkouts and disjoint scopes; never duplicate active tasks or judges.
Run affected repository checks directly, for example:

```powershell
npm run test:devloop
npm run check
```

Choose checks appropriate to the change. Documentation-only work needs diff/link
and formatting checks, not invented app-test claims. Record actual commands and
outcomes. Native coding, offline checks and read-only Proof verification require
no Meta configuration or Muse launcher. A missing
C:/Users/User/.meta-budget/settings.json is not a prerequisite for these operations.
Do not create dummy settings or copy settings/secrets from a teammate.

## Review and publish

After two unsuccessful repairs, obtain one targeted diagnosis. If the subsequent
bounded repair remains blocked, checkpoint and stop. Obtain a fresh independent
Sol/Terra review of the complete green diff with a bounded packet. Limit final
review repairs to two attempts. Before authorized push/publication, verify the exact
reviewed head with passing appropriate local checks. Before merge, all required
remote checks must pass on the exact reviewed published head. Record branch,
candidate commit, owned paths, actual
checks, review result, repair count, unresolved blockers and next action.

## Live and physical evidence

Meta/Muse/OpenCode coding and coding compaction remain disabled. Preserve both
external STOPs and keep FORMA-Claude-Handoff disabled. MetaMuse remains the app's
runtime brain; actual live calls require existing guarded runtime prerequisites.
META_GUARD_HOME means a machine-specific existing settings directory, not an
installer or portable profile path. Never create dummy settings or copy secrets.

The external live verification window was expired at this handoff. Do not renew
it or run calls unless existing controls permit them. Preserve bounded
reservations/outcomes, journals and unknown-outcome halting; keep keys server-only
and payments unchanged. Report actual provider usage. Live acceptance probes run
only while coding workers are idle.

Keep offline-engine expansion paused and focus on connected-demo integration.
Missing real measurements/photos or physical tests remain explicit physical
acceptance blockers. Fixtures and offline checks cannot replace that evidence.
Keep native automatic compaction enabled; claim it only with a runtime event.
