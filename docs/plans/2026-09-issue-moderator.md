# Issue moderator: Claude-driven bug/feature triage in GitHub Actions

## Status

Draft

## Goal

Add GitHub Actions workflows that run the `claude` CLI as an issue
moderator: on a bug report, verify it's actionable, reproduce it as a
failing test on a branch, and ask the reporter to confirm before a
second workflow fixes it and opens a PR; on a feature request, verify
it fits the project, draft a plan on a branch, and ask for confirmation
before a second workflow implements it and opens a PR. This turns
`docs/plans/README.md`'s "explore, then plan, then implement" workflow
into something that runs against real issues without a human driving
Claude Code interactively for the initial triage/repro/plan step. Also
covers the rest of the issue's lifecycle, not just the happy path to a
PR: if the reporter closes the issue before confirming, or without ever
merging the resulting PR, the branches and PRs this pipeline created
get cleaned up rather than left dangling.

## Approach

### State machine (labels)

Two independent label sequences drive the two flows; each stage's
workflow only acts on issues carrying its expected starting label(s),
so a job never re-triggers itself:

- Bug: `bug` → (`needs-info` | `bug:repro-ready`) → `bug:confirmed` →
  `bug:fixed` (added once the fixer opens a PR; the original `bug`
  label stays for search/reporting).
- Feature: `enhancement` → (`enhancement:not-a-fit` |
  `enhancement:plan-ready`) → `enhancement:confirmed` →
  `enhancement:built`.

Add these labels to the repo (a short `gh label create` block in a
setup step, or documented as a one-time manual step — see open
questions) plus a `claude:ok` label used as the trust gate below.

**Reopening restarts triage from scratch.** Whatever state a bug/
feature issue was in when it was closed, reopening it strips every
`bug:*`/`enhancement:*` stage label back down to the bare `bug`/
`enhancement` label and re-runs triage job 1/3 as if the issue were new
— it does not resume from `bug:repro-ready`, `bug:confirmed`, etc. The
repo may have changed since any branch from a prior run was created (or
that branch/PR may already be gone via job 5's cleanup), so re-deriving
a fresh repro/plan is more reliable than trying to validate and resume
stale state.

### Trust gate (required before any of this runs)

Both triage jobs and both confirmation jobs must skip unless the
triggering user is trusted: `github.event.issue.author_association` is
one of `OWNER`, `MEMBER`, `COLLABORATOR`, **or** the issue already
carries a `claude:ok` label (a maintainer opts an external report in).
Reasoning: the issue body and every comment on it are untrusted text
that flows straight into a Claude prompt, and this pipeline pushes
branches, spends the `ANTHROPIC_API_KEY` budget, and opens PRs from
repo secrets — an external reporter should not be able to get code
executed or credentials touched purely by opening an issue with a
crafted body. This mirrors the "IMPORTANT" prompt-injection caution
already called out for this kind of dual-use automation.

### Workflow files

All four jobs run the `claude` CLI the same way `checks.yml` runs
`prek` — inside the actual devcontainer's `develop` stage, via
`devcontainers/ci`, so Claude runs the exact CLI build already pinned
there (`Dockerfile`'s `CLAUDE_CODE_VERSION` ARG, Renovate-tracked, same
one an interactive Claude Code session in this repo uses) instead of a
second, independently-versioned install. No `npm install` step needed
in the workflow itself — the image already has it.

Before the `devcontainers/ci` step, a workflow step writes the
`ANTHROPIC_API_KEY` GitHub Actions secret out to `.secrets/claude.txt`
(created fresh each run, `chmod 600`), matching this repo's existing
"one file per secret under `.secrets/`" convention (`.secrets/README.md`)
instead of inventing a CI-only delivery mechanism — the same file a
contributor would drop their own key into for local use. A shared step
(`.github/scripts/run_claude.sh`, per `.github/scripts/README.md`'s
"keep workflow logic longer than a few lines in scripts/" rule) then
runs inside the container:

```yaml
- name: Write Claude API key
  run: |
    install -m 600 /dev/null .secrets/claude.txt
    printf '%s' "${{ secrets.ANTHROPIC_API_KEY }}" > .secrets/claude.txt
- uses: devcontainers/ci@v0.3
  with:
    runCmd: .github/scripts/run_claude.sh "<prompt-file>" "<allowed-tools>"
```

`run_claude.sh` reads the key
(`export ANTHROPIC_API_KEY="$(cat .secrets/claude.txt)"`), configures a
dedicated git identity (e.g. `claude-moderator[bot]`) for every commit
this pipeline makes, and invokes `claude -p "$(cat "$1")" --model
claude-sonnet-5 --effort medium --output-format json --allowedTools
"$2"` with the resource limits below. The container teardown step from `checks.yml` (unique
`COMPOSE_PROJECT_NAME`, `docker compose down --volumes
--remove-orphans` with `if: always()`) is reused verbatim, and a final
`if: always()` step removes `.secrets/claude.txt` from the runner
regardless of outcome (it's already `.gitignore`d and the runner is
ephemeral, but deleting it promptly keeps the key off disk for the
rest of the job).

1. **`.github/workflows/moderate-bug-triage.yml`**
   Trigger: `issues: [opened, reopened]`, filtered to the `bug` label.
   Steps: checkout, trust gate, a reset step (on `reopened` only: strip
   any `bug:needs-info`/`bug:repro-ready`/`bug:confirmed`/`bug:fixed`
   label, and if job 5 hasn't cleaned up yet — e.g. reopened seconds
   after closing — close any still-open PR and delete any leftover
   `bug/<issue-number>-repro` branch first, so triage starts from a
   clean slate), then run Claude with a prompt that:
   a. Reads the issue body against the "steps to reproduce" /
      "expected" / "actual" fields from `bug_report.yml`, plus enough
      of the repo (via read-only tools) to judge whether it's
      internally consistent and actionable.
   b. If information is missing/contradictory: comment asking specific
      follow-up questions, label `needs-info`, stop.
   c. Otherwise: create branch `bug/<issue-number>-repro`, write a
      failing test that reproduces the bug (and only that — no fix),
      run the project's test command to confirm it fails for the
      expected reason (not an unrelated error), commit, push.
   d. Comment on the issue with a link to the branch/diff and a
      summary of the failing test, asking the reporter to reply
      `/confirm` if this matches what they're seeing, label
      `bug:repro-ready`.

2. **`.github/workflows/moderate-bug-fix.yml`**
   Trigger: `issue_comment: [created]` on issues labeled
   `bug:repro-ready`.
   Steps: checkout, confirmation gate (commenter must be the original
   reporter — `github.event.comment.user.login ==
   github.event.issue.user.login` — *and* the comment body, trimmed,
   is exactly `/confirm`); anything else no-ops. `/confirm` is the
   standard slash-command shape already used by comment-triggered GitHub
   Actions across the ecosystem (`/lgtm`, `/retest`, etc. via tools like
   `peter-evans/slash-command-dispatch`), so it reads as a command
   rather than conversational text and is easy to `if:`-match on. On
   match:
   check out the `bug/<issue-number>-repro` branch, run Claude with a
   prompt to make the failing test pass without weakening or deleting
   it, run the full check suite
   (`uv run prek run --all-files --hook-stage manual`), commit, push,
   open a PR against `main` that references the issue (`Fixes #N`),
   relabel `bug:confirmed` → `bug:fixed`.

3. **`.github/workflows/moderate-feature-triage.yml`**
   Trigger: `issues: [opened, reopened]`, filtered to the `enhancement`
   label.
   Steps: checkout, trust gate, the same reset step as job 1 (stripping
   `enhancement:not-a-fit`/`enhancement:plan-ready`/
   `enhancement:confirmed`/`enhancement:built` and clearing any leftover
   `feature/<issue-number>-plan` branch/PR on `reopened`), then run
   Claude with a prompt that:
   a. Reads the issue's Problem/Proposed solution/Alternatives fields
      against the repo's README/ADRs/CLAUDE.md to judge fit (does it
      duplicate existing functionality, contradict an ADR, belong in a
      different layer, etc. — using the same "read the READMEs on the
      path" rule this repo already asks of Claude Code).
   b. If it doesn't fit: comment explaining why, label
      `enhancement:not-a-fit`, stop.
   c. Otherwise: create branch `feature/<issue-number>-plan`, write a
      plan document under `docs/plans/` per its own `template.md` and
      `README.md` filename convention, commit, push.
   d. Comment on the issue with the plan's Goal/Approach summary and a
      link to the plan file on that branch, asking the reporter to
      reply `/confirm` if the plan looks right, label
      `enhancement:plan-ready`.

4. **`.github/workflows/moderate-feature-build.yml`**
   Trigger: `issue_comment: [created]` on issues labeled
   `enhancement:plan-ready`.
   Steps: mirrors job 2 — confirmation gate (original reporter +
   exact `/confirm` match), check out `feature/<issue-number>-plan`,
   run Claude against the committed
   plan file to implement it, update the plan's `Status` to `Done` and
   fold anything ADR-worthy per `docs/plans/README.md` (then remove the
   plan file, per that same "don't leave a finished plan in place"
   rule), run the full check suite, commit, push, open a PR referencing
   the issue, relabel `enhancement:confirmed` → `enhancement:built`.

5. **`.github/workflows/moderate-cleanup.yml`**
   Trigger: `issues: [closed]`. Runs unconditionally — no trust gate
   and no Claude invocation at all, since it only tidies up git/PR
   state via `gh`, so there's no prompt-injection or spend surface to
   guard.
   Steps: checkout, then via `gh`:
   a. Look up any PR whose branch matches this issue
      (`bug/<n>-repro` or `feature/<n>-plan` — one branch is reused
      across triage → fix/build in both flows, per jobs 1-4 above) or
      whose body references `Fixes #<n>` / `Closes #<n>`.
   b. If that PR is already **merged**: the issue closed via the normal
      "merge closes the linked issue" path — nothing to reconcile
      beyond deleting the branch if the repo's own "auto-delete branch
      on merge" setting didn't already do it (idempotent: skip if
      already gone).
   c. If that PR is **open** (issue was closed manually — by the
      reporter losing interest, a maintainer deciding not to proceed,
      etc. — without merging): close the PR with a comment explaining
      it was closed because the linked issue was, then delete the
      branch.
   d. If there's **no PR yet** but a repro/plan branch exists (issue
      closed before `/confirm`, e.g. while sitting in
      `bug:repro-ready`/`enhancement:plan-ready`, or even mid-triage):
      delete that branch. Nothing to do if triage never ran (issue
      closed straight from `bug`/`enhancement` with no branch created).
   e. Uses the same per-issue `concurrency:` group as the fix/build
      workflows (see "Resource limits" below) so a close landing while
      a fix/build job is mid-run doesn't race it — the fix/build job
      finishes (or times out) first, then cleanup runs against
      whatever state it left.

### Resource limits

Every job caps how much Claude can do unattended, so a runaway prompt
(from a malformed issue, a model that keeps retrying, or a prompt-
injection attempt) fails closed instead of burning CI minutes or API
spend:

- **Wall-clock**: a `timeout-minutes:` on each job (triage jobs: 10;
  fix/build jobs: 20 — they run the full check suite too), plus a
  `timeout` in front of the `claude` invocation itself inside
  `run_claude.sh` (e.g. `timeout 120s claude ...` for triage's
  analysis/decision step; a longer explicit budget, not the same 120s,
  for the fix/build step's edit-run-check loop, since that genuinely
  needs several tool-call round trips). A killed run leaves the issue
  in its current label state and the job's `if: always()` cleanup
  still tears down the devcontainer stack.
- **Turns**: `claude --max-turns` bounded per stage — **15** for the
  two triage jobs (read-mostly: read the issue, read some repo context,
  decide) and **40** for the two fix/build jobs (need edit/run-checks/
  re-edit cycles), so a job ends deterministically on turn exhaustion
  rather than only on wall-clock. Both are starting defaults to revisit
  once real runs show whether either stage routinely gets cut off.
- **Model/effort**: every `claude -p` invocation pins `--model
  claude-sonnet-5 --effort medium` explicitly rather than inheriting
  whatever default the pinned CLI version ships with, matching the
  model/effort already used for interactive work in this repo. Applies
  uniformly to all four stages (triage ×2, fix/build ×2) — none of them
  need a heavier model or effort level to start; revisit per-stage only
  if real runs show a specific stage under-performing at medium.
- **Spend**: `claude` itself has no per-invocation spend-limit flag —
  the actual control surface is the Anthropic Console. Use a dedicated
  Console **workspace** (not the default one) scoped to this pipeline,
  with its own `ANTHROPIC_API_KEY`, a **monthly spend limit** (default
  **$15/month** — a starting cap sized to see a few weeks of real
  triage/fix volume before committing to a higher number; raise it once
  usage data justifies it) and a usage alert at 80% of that limit, so
  the workspace itself hard-stops spend instead of relying only on
  turns/wall-clock to bound cost.
- **Concurrency**: a `concurrency:` group keyed on the issue number
  (e.g. `moderate-issue-${{ github.event.issue.number }}`), shared
  across **all five** workflows, so a burst of comments can't launch
  overlapping fixer/builder jobs against the same branch, a close
  landing mid-run doesn't race cleanup against an in-flight fix/build
  job, and a rapid close-then-reopen serializes cleanup (job 5) before
  the reopened triage's reset step, rather than the reset racing a
  cleanup that's still deleting the same branch.

## Shared guardrails

- `permissions:` on every workflow: `contents: write`, `issues: write`,
  `pull-requests: write`, and nothing broader — matching
  `.github/workflows/README.md`'s existing "narrowest permissions"
  pattern for `release.yml`/`template-sync.yml`.
- Every Claude invocation gets an explicit `--allowedTools` list (git,
  the project's test/lint commands, file read/write under the repo) —
  never an unrestricted/`--dangerously-skip-permissions` run, since the
  prompt includes untrusted issue text.
- Every job that pushes/opens a PR runs the same check suite the
  existing `checks.yml` runs, so a Claude-authored change can't merge
  without passing what a human-authored one would.
- Branches and PRs are always opened, never auto-merged. Merging stays
  a human decision, gated by normal branch-protection review — repo
  owners/members/collaborators are the ones who approve and merge the
  PR; this pipeline's own "confirm" step (open questions, resolved
  below) only gates whether Claude starts *building* something, not
  whether it ships.
- If Claude can't reproduce the bug / can't make the fix pass checks /
  can't complete the feature per the plan, it comments what it tried
  and why it stopped, and labels the issue `needs-human` instead of
  leaving it silently stuck.

## Open questions

- Who owns creating/rotating the dedicated Anthropic Console workspace
  and API key, and storing it as the `ANTHROPIC_API_KEY` repository
  secret.
- Confirm `--max-turns`, `--model`, and `--effort` are still the
  correct flag names (and check for any spend/budget-related flag added
  since — none exists as of this writing) against the CLI version
  actually pinned in the `Dockerfile` at implementation time — flag
  names can change between releases.
- Whether to hand-roll the CLI invocation (as sketched above) or use
  the maintained `anthropics/claude-code-action` GitHub Action, which
  already handles auth, git identity, and permission-mode wiring, at
  the cost of not running inside this repo's own pinned devcontainer —
  recommend the hand-rolled `devcontainers/ci` route above so the CLI
  version and environment stay single-sourced from the `Dockerfile`,
  unless `claude-code-action` turns out to support that directly.
- One-time repo setup (label creation, any branch-protection interplay
  with bot-opened PRs) isn't itself a workflow step; needs to happen
  once, manually or via a `workflow_dispatch` bootstrap job.
