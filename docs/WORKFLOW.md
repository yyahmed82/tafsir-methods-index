# Review workflow — roles, assignment, reminders, retries, publishing

How a unit goes from the AI committee to mirqah.app, and who does what. The console
(`console/`) implements all of it; nothing here needs a git merge.

```
 committee run ──► chair decides ──► chair assigns the window ──► specialist decides ──► super admin publishes ──► mirqah.app
 (AI suggests)      (code, ≥85)        (least-loaded specialist,      (approve / needs edit /    (versioned snapshot,          (reads the live
                                        X and Y together)              reject, compared first)    rollback = one click)          snapshot only)
        ▲                                     │ 09:00 reminder until decided
        └── failed step: retry 5 min, 30 min ─┴── still failing → e-mail operators + super admins
```

## Roles

- A user can hold **several roles**. Their permissions are the union of those roles.
  The primary role (shown first) is picked by rank: super admin, operator, specialist, viewer.
- **Only the Specialist role decides** (approve / needs edit / reject). A super admin or
  operator who reviews adds the Specialist role to their own account (Users → Edit).
  Anyone holding the Specialist role reviews blind: arm X / Y is never revealed to them.
- **Only super admins publish** (permission `publish_units`).
- CLI: `sudo mirqah create-user --email … --name "…" --role super_admin,specialist`.
  For an existing user the roles are **added**; remove roles in the console.

| | Super admin | Committee operator | Specialist | Viewer |
|---|---|---|---|---|
| Run tasks, retry, cancel | ✓ | ✓ | | |
| Reassign a window | ✓ | ✓ | | |
| Decide (approve / edit / reject) | only with the Specialist role | only with the Specialist role | ✓ (own windows) | |
| Publish to mirqah.app, roll back | ✓ | | | |
| Settings, users, roles | ✓ | | | |

## Assignment and reminders

- After every chair step the chair gives the window — **both blind versions X and Y
  together** — to the specialist with the fewest open moves (Settings → Workflow →
  auto-assign). A sweep every 5 minutes catches anything missed and moves work away from
  someone who lost the Specialist role or was deactivated.
- Only the assignee decides a window. An operator or super admin can reassign it from the
  review page. A window no one holds yet becomes the deciding specialist's.
- The window closes when every move in it has a decision.
- **09:00 Riyadh** (Settings → Workflow): one e-mail per specialist listing their open
  windows, every day until they are decided.
- **21:00 Riyadh** (Settings → Reports): the daily report to operators and super admins
  now has each specialist's desk (open windows, open moves, oldest, decided today) and the
  **chair's suggestions** — too few specialists, old or unbalanced work, failures, loops,
  context limits, units waiting to be published. Suggestions are plain rules, not AI.

### Remind now, and the Performance page

- **Remind** (operators and super admins): on the Performance page next to each specialist,
  and on a window's assignment bar. It e-mails that one person the windows still waiting
  for them. At most once an hour per person; the 09:00 e-mail counts, and the 09:00 batch
  skips anyone reminded by hand within the hour. Written to the audit log
  (`review.remind_one`).
- **Performance** (top bar, `#/team`): the history behind the work, next to mission
  control's live view. Period 7 / 30 / 90 days or a year (weeks and months for the long
  ones).
  - Specialists: decisions (approve / needs edit / reject), what is waiting now, median time
    from assignment to clearing a window, oldest waiting, lessons taught, specialists vs the
    minimum; decisions per day (stacked per person) with milestone markers; a table per
    person with the Remind button; milestones (first decision, 50/100/250… decisions, first
    lesson, desk cleared, team totals, versions published).
  - Agents: steps done, failed in the end, saved by a retry, classifier median time, tokens
    in/out; steps per day per agent with failures; per agent: done, failed, saved by retry,
    median, p95, tokens and why steps failed; what humans decided on moves the chair
    suggested vs referred (routing guidance, not accuracy).
  - Who sees what: operators and super admins see every specialist; a specialist sees their
    own numbers and the team totals; anyone else sees team totals. The baseline vs profile
    comparison is hidden from anyone holding the Specialist role (blind review).
  - Works in demo mode (the simulated year) for the video.

## Automatic retries and alerts

| What happened | What the console does | Attempt used? |
|---|---|---|
| Step failed (model error, invalid reply, timeout) | retry after 5 min, then 30 min | yes (2 retries) |
| Model engine offline (Mac asleep, Tailscale down) | wait and try every minute | no |
| Console restarted mid-step | run the step again on start (up to 3 times) | no |
| Reply loops (repeats itself) | stopped early; re-asked once with a little temperature | — |
| Still failing after the retries | counted as failed; e-mailed to operators + super admins | — |

- Alerts are batched (at most one e-mail every 10 minutes); an offline engine is e-mailed at
  most once an hour while steps wait for it.
- A step that waits for a retry keeps its place; the steps that depend on it (method
  specialist, chair of the same window) wait for it.
- "Retry failed steps" still gives a fresh set of attempts.

### Retries belong to their original task

- A manual **Retry failed steps** is not a new, unrelated task: it is **retry n of the
  original** (`tasks.origin_id`, `tasks.retry_of`). Pressed on the original or on any of its
  retries, it runs only the steps whose **last** outcome in the whole chain is still open
  (failed, interrupted, or skipped because an earlier agent had no result), and it is refused
  while another attempt of the same chain is queued or running.
- The task list shows **one row per original** with the combined result (the last outcome of
  every step) and a ↻ n button that folds the attempts open under it: original run, retry 1,
  retry 2 … each with its own counts and the cause (timed out, console restart, engine
  offline, model looped, missing input). A chain that ends clean shows *done · fixed by
  retry ×n*; the original keeps its own counts as history.
- The task page has an **Attempts** card (all attempts, the final result) and, on the
  original, a *fixed in #n* link on every step a later attempt finished.
- When the classifier of a window fails, its method specialist is **skipped** (no result to
  review), not counted as a second failure; the retry runs it again after the classifier.
- Older retries (linked only by `params.retry_of`) are grouped automatically on start.

## Publishing (no git merge)

- **Publish** page (super admins): what is approved now, what would change on mirqah.app
  (new / changed / removed), and checks — each approved unit is re-verified against the
  pinned source (`sha256` and exact text); failures are held back with the reason.
  Identical units approved in both blind versions are merged; overlapping units with
  different methods are listed for a look.
- **Publish vN** writes `VAR_DIR/published/vNNNN.json` and makes it live. The history keeps
  every version; **Make live** on an older one is the rollback.
- The public, read-only address is `https://console.mirqah.app/public/v1/published.json`
  (`manifest.json` next to it). No login, cached 60 s, ETag, CORS open, **no reviewer
  names or e-mails** — who approved and who published stays in the console and the audit log.
- mirqah.app does not read it yet: see [PUBLIC_SITE_CLEANUP.md](PUBLIC_SITE_CLEANUP.md).
