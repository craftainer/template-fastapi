# Pre-flight runbook: packages, performance and observability plan

Step-by-step setup for the user to complete **before** kickoff (gate G0)
of [`2026-10-packages-performance-observability.md`](2026-10-packages-performance-observability.md).
Each step says where to click or what to run, and how to check it worked.
Steps 3–5 need an owner of the `craftainer` GitHub organization.

This file belongs to the plan and is deleted with it.

## Checklist

- [ ] 1. Merge PR #35 (plan update)
- [ ] 2. Rebuild the devcontainer
- [ ] 3. PyPI and TestPyPI: pending trusted publishers
- [ ] 4. Org secret `TEMPLATE_SYNC_TOKEN`
- [ ] 5. Org apps and rulesets (Renovate, CodSpeed, branch ruleset)
- [ ] 6. Claude Code permission allow-list
- [ ] 7. Docker resources and power settings
- [ ] 8. Start a fresh session and kick off

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

### 5c. Branch ruleset for the new repos

Mirrors `template-fastapi`'s own ruleset, so every new repo is protected
from its first commit.

<https://github.com/organizations/craftainer/settings/rules> → **New
ruleset → New branch ruleset**:

| Setting | Value |
| --- | --- |
| Name | `default-branch` |
| Enforcement | Active |
| Target repositories | By name: `tool-*` and `template-python-package` (or all repositories) |
| Target branches | Include default branch |
| Restrict deletions | ✓ |
| Block force pushes | ✓ |
| Require a pull request before merging | ✓, allowed merge method: **Squash** |
| Require status checks to pass | ✓, add `prek (amd64, ubuntu-24.04)` and `prek (arm64, ubuntu-24.04-arm)`, the exact check names `checks.yml` reports (copied from `template-fastapi`'s `main`) |

**Check:** the ruleset shows as *Active* with the targets above.

## 6. Claude Code permission allow-list

Keeps 18 parallel agents from prompting for every routine command. It
goes in your **personal, git-ignored** file (listed in `.gitignore`),
not the template-synced `.claude/settings.json`. Subagents inherit the
main session's rules.

Create `/workspace/.claude/settings.local.json`:

```json
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(uv *)",
      "Bash(uvx *)",
      "Bash(prek *)",
      "Bash(git *)",
      "Bash(gh *)",
      "Bash(docker *)",
      "Bash(locust *)",
      "Bash(py-spy *)",
      "Bash(python3 *)",
      "Bash(make *)",
      "Bash(curl -s https://pypi.org/*)",
      "WebSearch",
      "WebFetch",
      "mcp__plugin_context7_context7__*"
    ],
    "deny": [
      "Bash(uv publish *)",
      "Bash(twine *)",
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Bash(git push origin main*)",
      "Bash(gh repo delete *)",
      "Bash(gh pr merge *)",
      "Bash(gh release create *)"
    ]
  }
}
```

The `deny` list enforces your decisions mechanically:
- no manual PyPI uploads;
- no force pushes and no direct pushes to `main`;
- no deleting repos;
- you merge PRs yourself;
- releases only through workflows.

Deny always wins over allow.

**Check:** in the fresh session (step 8), `/permissions` lists these
rules.

## 7. Docker resources and power settings

- Docker Desktop → **Settings → Resources**: at least **16 GB** memory
  and **100 GB** free disk. 18 worktrees each get their own `.venv`, and
  perf runs build images.
- Turn off sleep for the duration of the run (Windows: *Power & sleep →
  Never*; macOS: *Battery/Energy → Prevent automatic sleeping*).

**Check** (in the container):

```bash
docker info --format 'mem={{.MemTotal}} cpus={{.NCPU}}'; df -h /workspace
```

## 8. Start a fresh session and kick off

1. Open a **new** Claude Code conversation in VS Code. Don't continue the
   planning conversation; the orchestrator should start with a clean
   context.
2. Check that `/agents` lists **plan-executor**, `/mcp` shows context7
   connected, and `/permissions` shows step 6's rules.
3. Send:

   > Execute `docs/plans/2026-10-packages-performance-observability.md`
   > as orchestrator, per `CLAUDE.md`. The pre-flight runbook is
   > complete (steps 1–8). G0 is granted.

From here, the orchestrator only comes back to you for PR merges
(G-pr, batched per wave), releases (G-rel), real escalations (G-esc),
and the final close-out (G-final).
