# v0.5.0 external-feedback launch checklist

## Scope

This checklist governs review and possible later publication of the v0.5.0
drafts in this directory. Completing the draft packet does **not** authorize a
post, message, push, release operation, paid service, telemetry, or provider
execution.

Every external channel requires an explicit human approval after the final
channel-specific copy is shown. Approval for one channel does not authorize
another channel or later repost.

## Current public-fact snapshot

Read-only checks performed on 2026-07-14:

| Fact | Verified public surface | Snapshot |
| --- | --- | --- |
| Repository | https://github.com/mocchalera/project-loop-harness | Public repository; default branch `main`; MIT license |
| GitHub release | https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0 | `v0.5.0`, non-draft, non-prerelease; published 2026-07-14 13:02:06 UTC |
| Release tag target | Public Git tag `v0.5.0` | Peeled commit `6bfe9b4a5c5b651c7a4f5c7f4771e65cfa75fdb8` |
| PyPI | https://pypi.org/project/project-loop-harness/0.5.0/ | Latest version `0.5.0`; wheel and sdist uploaded 2026-07-14 |
| Python/runtime metadata | PyPI JSON and `pyproject.toml` | Python `>=3.10`; no required runtime dependencies |

### Known publication inconsistency — resolve before posting

The GitHub Release exists publicly, but its body was copied from the local RC
note and still says **“Local release candidate; not published”** and that
publication requires a later action. This contradicts the public release and
PyPI state.

- [ ] Human owner decides whether to correct the GitHub Release body.
- [ ] If corrected, re-open the public Release and save the checked timestamp.
- [ ] If not corrected, do not quote or link readers to the contradictory status
      text without a clear explanation.

Updating the Release body is an external GitHub write and is outside this draft
task. Do not perform it without separate explicit approval.

## 1. Human approval gate

- [ ] Name the human approver: `________________`.
- [ ] Record approval timestamp and timezone: `________________`.
- [ ] Select exactly one first channel: `Zenn / Hacker News / Reddit / other`.
- [ ] Record the exact destination/community: `________________`.
- [ ] Show the approver the final title and body as they will appear.
- [ ] Confirm the poster's maintainer affiliation is disclosed.
- [ ] Confirm the post asks for feedback and does not imply broad adoption.
- [ ] Confirm the reply/issue owner and monitoring window.
- [ ] Obtain a separate approval for any cross-post, repost, direct message, or
      material copy change.
- [ ] Confirm no automated posting or messaging credential will be used by this
      task.

Approval record:

```text
Channel:
Destination:
Final-copy path or hash:
Approved by:
Approval source/reference:
Approved at:
Posting window:
Reply owner:
```

## 2. URL verification immediately before posting

Open each link in a clean or logged-out browser, not only through a maintainer
session.

- [ ] Repository loads: https://github.com/mocchalera/project-loop-harness
- [ ] README anchor loads: https://github.com/mocchalera/project-loop-harness#readme
- [ ] v0.5.0 Release loads: https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0
- [ ] PyPI v0.5.0 loads: https://pypi.org/project/project-loop-harness/0.5.0/
- [ ] Adoption Guide loads on `main`: https://github.com/mocchalera/project-loop-harness/blob/main/docs/adoption-guide.md
- [ ] Issues page loads: https://github.com/mocchalera/project-loop-harness/issues
- [ ] Relative links in the selected draft resolve in its intended renderer.
- [ ] No link points to a local path, private worktree, unpublished branch, or
      mutable artifact presented as immutable proof.

Optional command-line check (redirects allowed, success must end in 2xx):

```bash
curl -fsSIL https://github.com/mocchalera/project-loop-harness
curl -fsSIL https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0
curl -fsSIL https://pypi.org/project/project-loop-harness/0.5.0/
curl -fsSIL https://github.com/mocchalera/project-loop-harness/blob/main/docs/adoption-guide.md
```

## 3. Claim verification

Re-check claims against repository files and public metadata on the posting day.

| Claim | Required evidence | Pass |
| --- | --- | --- |
| v0.5.0 is public | GitHub Release API/page and PyPI version page agree | [ ] |
| Release date/time | Public GitHub/PyPI metadata, with timezone stated if used | [ ] |
| Core is local and model-neutral | README architecture and initialization boundary | [ ] |
| SQLite is current-state system of record | README/CLAUDE architecture wording | [ ] |
| JSONL is audit projection; HTML is human view | README/AGENTS architecture wording | [ ] |
| No required runtime dependencies | `pyproject.toml` plus PyPI `requires_dist` (ignore named extras) | [ ] |
| Python support | PyPI `requires_python` and release docs agree | [ ] |
| No telemetry/cloud sync/provider call/automatic GitHub write on init | README and release boundary | [ ] |
| Existing instructions/config are preserved by normal init | README and Adoption Guide exact boundary | [ ] |
| Council is opt-in/experimental/advisory | README and v0.5.0 release scope | [ ] |
| Direct remains default | README Council section and release notes | [ ] |
| Real network/paid provider work is outside Core and human-authorized | README Council section | [ ] |

Run a wording search over the selected final draft:

```bash
rg -ni 'users?|customers?|downloads?|stars?|forks?|better than|best|leading|production[- ]ready|telemetry|council|provider|automatic github' FINAL_DRAFT.md
```

For every match:

- [ ] Remove an unneeded adoption, popularity, competitor, or superiority claim.
- [ ] Attach dated public evidence for a necessary factual claim.
- [ ] Keep feedback-study results in the form “N of 3 study participants,” with
      date and recruitment context.
- [ ] Do not turn absence of telemetry into absence of all network access;
      `pcl update check` is an explicit advisory PyPI metadata request.
- [ ] Do not call Council a provider, executor, verifier, approval, or default.
- [ ] Do not describe alpha software as production-ready.

## 4. Copy and channel review

- [ ] Remove the editorial draft note from the published copy.
- [ ] Preview code blocks, headings, and links in the destination renderer.
- [ ] Confirm the title fits the channel and avoids unsupported superlatives.
- [ ] Confirm the first paragraph states the problem before product vocabulary.
- [ ] Confirm the quick start uses the public package name exactly:
      `project-loop-harness`.
- [ ] Confirm feedback questions are answerable without sharing sensitive data.
- [ ] Read the destination's current self-promotion and posting rules.
- [ ] For HN, use `Show HN` only if the public artifact is usable at posting time.
- [ ] For Reddit, tailor the post to one named community; do not assume one
      community's approval authorizes another.
- [ ] Save the approved final copy or content hash before posting.

## 5. Post-publication reaction record

Record reactions manually. Do not add telemetry, scrape identities, or copy
private messages into the repository without consent.

```text
Launch record ID:
Channel and URL:
Posted by:
Posted at:
Approved-copy path or hash:

Observation ID:
Observed at:
Public source URL:
Category: comprehension | install | dry-run | first-value | state-model |
          human-gate | council-boundary | bug | request | other
Summary (paraphrase; no unnecessary personal data):
Verbatim quote permitted? yes / no
Reproduction steps:
Evidence link:
Severity: blocker | major | minor | note
Response status: acknowledged | asked-for-details | reproduced | fixed | deferred | rejected
Owner:
Next review date:
```

Daily synthesis during the agreed monitoring window:

- [ ] Count unique observations, not accounts or presumed users.
- [ ] Separate questions, preferences, reproducible defects, and safety issues.
- [ ] Link product/copy changes to observation IDs.
- [ ] Record negative and neutral feedback, not only favorable comments.
- [ ] Do not infer usage from votes, views, stars, installs, or comments unless
      the metric source and interpretation are explicitly approved.
- [ ] Ask before sending any direct reply, message, or follow-up post if that
      action was not included in the posting approval.

## 6. Stop and escalation conditions

Pause further posting and ask the human owner when:

- the GitHub, PyPI, tag, or package-version surfaces disagree;
- install instructions fail from the public package;
- a security, privacy, destructive-operation, or credential-handling concern is
  reported;
- readers repeatedly infer that Council approves or executes provider work;
- readers repeatedly infer that initialization enables telemetry or external
  writes;
- a channel moderator removes the post or requests a change;
- the approved copy needs a material claim change;
- a reply would commit to a roadmap, support obligation, or release date.

## 7. Close the launch-feedback round

- [ ] Human owner reviews the reaction record and the three-person study.
- [ ] Each proposed change is marked `adopt`, `defer`, or `reject` with evidence.
- [ ] Safety and factual inconsistencies are handled before copy polish.
- [ ] Any code/docs follow-up is opened as separately scoped work.
- [ ] No user/customer/adoption claim is created from this small qualitative
      round.
- [ ] Record whether another feedback round is approved; do not schedule or post
      it automatically.
