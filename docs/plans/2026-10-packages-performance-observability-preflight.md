# Pre-flight runbook: packages, performance and observability plan

Step-by-step setup for the user to complete **before** kickoff (gate G0)
of [`2026-10-packages-performance-observability.md`](2026-10-packages-performance-observability.md).
Each step says where to click or what to run, and how to check it worked.
Steps 3–5 need an owner of the `craftainer` GitHub organization.

This file belongs to the plan and is deleted with it.

## Checklist

- [x] 1. Merge PR #35 (plan update)
- [x] 2. Rebuild the devcontainer
- [x] 3. PyPI and TestPyPI: pending trusted publishers
- [x] 4. Org secret `TEMPLATE_SYNC_TOKEN`
- [x] 5. Org apps and rulesets (Renovate, CodSpeed, branch ruleset)
- [x] 6. GitHub CLI: merge the base PR, sync, rebuild, log in
- [x] 7. Power settings
- [x] 8. Start a fresh session and kick off

---

## 1. Merge PR #35

Review and merge <https://github.com/craftainer/template-fastapi/pull/35>
(squash). It renames `health` to the observability package and adds
Phase 8 and this runbook.

**Check:** `git switch main && git pull` shows
`docs/plans/2026-10-packages-performance-observability-preflight.md`.

## 2. Rebuild the devcontainer

The template-base v1.3.0 sync moved the devcontainer image to
`.devcontainer/Dockerfile`. The running container was built from the old
root Dockerfile.

1. In VS Code: Command Palette (`Ctrl/Cmd+Shift+P`) → **Dev Containers:
   Rebuild Container**.
2. Wait for `postCreateCommand` to finish.

**Check** (in the rebuilt container's terminal):

```bash
prek run --all-files --hook-stage manual
```

Every hook shows `Passed` (or `Skipped`).

## 3. PyPI and TestPyPI: pending trusted publishers

Lets each package's `release.yml` publish through GitHub OIDC with no
stored token. Packages are never uploaded by hand (Decision log).

PyPI and TestPyPI are **separate accounts**. Do this on both:

| | PyPI | TestPyPI |
| --- | --- | --- |
| Account (with 2FA) | <https://pypi.org/account/register/> | <https://test.pypi.org/account/register/> |
| Publishing page | <https://pypi.org/manage/account/publishing/> | <https://test.pypi.org/manage/account/publishing/> |

On each publishing page, under **Add a new pending publisher → GitHub**,
add **two** entries:

| Field | Entry 1 | Entry 2 |
| --- | --- | --- |
| PyPI Project Name | `craftainer-tool-crud` | `craftainer-tool-observability` |
| Owner | `craftainer` | `craftainer` |
| Repository name | `tool-crud` | `tool-observability` |
| Workflow name | `release.yml` | `release.yml` |
| Environment name | *(leave empty)* | *(leave empty)* |

**Check:** each publishing page lists two pending publishers.

A pending publisher doesn't reserve the name. If someone else registers
either name before the first release, tell the orchestrator; picking a
new name means changing the plan.

**Don't** set a `PYPI_PUBLISH` variable at org level. It would also make
`template-python-package` try to publish. The orchestrator asks you
(gate G-rel) and sets it per package repo, right before each release.

## 4. Org secret `TEMPLATE_SYNC_TOKEN`

Template sync pushes changes under `.github/workflows/`, which the
default `GITHUB_TOKEN` can't do (`ADR-0018`). The three new repos need
this secret from the start.

1. Check whether it already exists:
   <https://github.com/organizations/craftainer/settings/secrets/actions>.
   If `TEMPLATE_SYNC_TOKEN` is listed with **Repository access: All
   repositories**, skip to step 5. If it exists with *Selected
   repositories*, switch it to **All repositories** (new repos aren't
   added to a selection automatically).
2. Otherwise create a fine-grained token:
   <https://github.com/settings/personal-access-tokens/new>
   - Resource owner: `craftainer`
   - Repository access: **All repositories**
   - Permissions → Repository: **Contents** read/write, **Pull
     requests** read/write, **Workflows** read/write (Metadata read is
     added automatically)
   - Expiration: your choice; note the date
3. Add it as an organization secret named `TEMPLATE_SYNC_TOKEN`, with
   **Repository access: All repositories**.

**Check:** the secrets page lists `TEMPLATE_SYNC_TOKEN` with access to
all repositories.

## 5. Org apps and rulesets

### 5a. Renovate

<https://github.com/organizations/craftainer/settings/installations> →
**Renovate** → **Configure** → **Repository access: All repositories** →
Save. If Renovate isn't installed, install it from
<https://github.com/apps/renovate>.

**Check:** the installation page shows *All repositories*.

### 5b. CodSpeed

1. <https://codspeed.io> → **Log in with GitHub**.
2. Install the CodSpeed GitHub App on `craftainer` with **All
   repositories**.

No secret is needed: CodSpeed accepts tokenless uploads from public
repositories.

**Check:** CodSpeed's dashboard lists the `craftainer` organization.

### 5c. Branch and tag rulesets for the new repos

Org rulesets aren't enforced on GitHub Free. The orchestrator instead
copies `template-fastapi`'s two repo-level rulesets ("Disallow direct
push to main", "Disallow tags except me") onto each new repo itself
(Decision log, 2026-10-18). The only thing for you to do: delete the
disabled `default-branch` org ruleset at
<https://github.com/organizations/craftainer/settings/rules>, so it
doesn't look like protection is in place.

## 6. GitHub CLI: merge the base PR, sync, rebuild, log in

`gh` used to be installed by hand, so the rebuild in step 2 dropped it.
The orchestrator needs it for PRs, workflow runs and releases. A
temporary copy is in `~/.local/bin/gh`; this step makes it permanent.

1. Log the temporary copy in, so the orchestrator can open the PRs:
   `gh auth login` (GitHub.com → SSH → browser). **Check:**
   `gh auth status` shows `Logged in`.
2. Review and merge the template-base PR that adds `gh` to the
   devcontainer (`feat/devcontainer-gh-cli`), then ask the orchestrator
   to release template-base and sync this repo (it opens the sync PR);
   merge that.
3. Rebuild the devcontainer again (Command Palette → **Dev Containers:
   Rebuild Container**), then run `gh auth login` once more. From now
   on, the login lives in the `gh-config` volume and survives rebuilds.
   **Check:** `which gh` prints `/usr/local/bin/gh`, and `gh auth
   status` shows `Logged in`.

Permissions need no setup: they're shared in the repo's
`.claude/settings.json` (`.claude/README.md` explains each rule).

## 7. Power settings

Turn off sleep for the duration of the run (Windows: *Power & sleep →
Never*; macOS: *Battery/Energy → Prevent automatic sleeping*).

With 8 GB of memory, the plan runs at most 4 agents at once (its
Decision log). Raising Docker's memory later doesn't change that cap
automatically: tell the orchestrator the new budget.

## 8. Start a fresh session and kick off

1. Open a **new** Claude Code conversation in VS Code. Don't continue the
   planning conversation; the orchestrator should start with a clean
   context.
2. Check that `/agents` lists **plan-executor**, `/mcp` shows context7
   connected, and `/permissions` shows the rules from `.claude/settings.json`.
3. Send:

   > Execute `docs/plans/2026-10-packages-performance-observability.md`
   > as orchestrator, per `CLAUDE.md`. The pre-flight runbook is
   > complete (steps 1–8). G0 is granted.

From here, the orchestrator only comes back to you for PR merges
(G-pr, batched per wave), releases (G-rel), real escalations (G-esc),
and the final close-out (G-final).
