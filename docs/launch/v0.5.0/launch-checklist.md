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

### Resolved publication inconsistency

The GitHub Release was initially published with a body copied from the local RC
note that still said **“Local release candidate; not published”**. The human
owner authorized correcting it after the launch packet review, and the public
Release body was updated on 2026-07-14 to the independently verified published
status.

- [x] Human owner authorized correcting the GitHub Release body in Cockpit Ask
      `ask_1e632aa9a84c`.
- [x] The public Release was re-opened after the edit; the stale phrase was
      absent and the published/independently-verified status was present.
- [ ] Re-check the Release body immediately before an external post, together
      with the other URLs and claims below.

Any later Release-body edit remains an external GitHub write and requires
separate explicit approval.

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

### Hacker News human-authorship boundary (2026-07-14)

The official Hacker News Guidelines now say not to post generated text or
AI-edited text. The existing HN title candidates and body in
`en-hn-reddit-draft.md` were AI-assisted and are therefore retained only as an
abandoned internal draft. They must not be submitted, adapted, or polished for
submission.

Any HN title, submission text, or first comment must be written from scratch by
the human poster without AI editing. Agents may perform a factual and rules
check without supplying replacement wording. The non-postable source and rules
packet is `hn-human-authoring-brief.md`.

- [x] Re-check the current official HN Guidelines, Show HN rules, and FAQ.
- [x] Mark the existing AI-assisted HN draft as ineligible for submission.
- [x] Preserve only public facts and source links in a non-postable human brief.
- [ ] Human writes a fresh HN title and any text from scratch without AI help.
- [ ] Agent performs a report-only fact/rules check with no rewriting.
- [ ] Human explicitly approves the independently written title, target URL,
      timing, and any first comment before posting.

### Zenn first-channel review (2026-07-14)

The human owner selected Zenn as the first channel in Cockpit Ask
`ask_2d2912fb7b9b`. The final review candidate is
`zenn-agent-done-evidence-pcl-v050.md`; it remains `published: false` until a
separate approval names the exact title and body.

The current official [community guideline](https://zenn.dev/guideline),
[Markdown guide](https://zenn.dev/zenn/articles/markdown-guide), and
[Zenn CLI guide](https://zenn.dev/zenn/articles/zenn-cli-guide) were checked.
The candidate was revised accordingly:

- it leads with a concrete engineering problem and reproducible dogfood result,
  rather than making product promotion the main content;
- the title describes the actual SQLite/JSONL/Evidence design without a
  superlative or adoption claim;
- headings begin at level 2, the five-topic front matter stays within the
  documented limit, and the public image uses supported URL/alt/caption syntax;
- the author/maintainer relationship is disclosed, and public/project-owned
  text and image assets are used;
- the three-person feedback plan is explicitly qualitative and is not presented
  as broad adoption evidence.

- [x] The selected final copy contains no editorial draft note.
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
