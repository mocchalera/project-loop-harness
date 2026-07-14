# Hacker News human-authoring brief for v0.5.0

This is an internal fact-checking and compliance brief, **not submission copy**.
Do not paste, paraphrase, or ask an AI to rewrite this file into a Hacker News
title, submission, or first comment.

Checked on 2026-07-14 against the official Hacker News
[Guidelines](https://news.ycombinator.com/newsguidelines.html),
[Show HN rules](https://news.ycombinator.com/showhn.html), and
[FAQ](https://news.ycombinator.com/newsfaq.html).

## Hard compliance boundary

- Hacker News says not to post generated text or AI-edited text.
- The existing HN draft in `en-hn-reddit-draft.md` was AI-assisted and is not
  eligible for submission or adaptation.
- The human poster must write the title and any text or first comment from
  scratch, in their own words, without AI editing.
- An agent may check independently written copy for factual conflicts, broken
  links, unsupported claims, or accidental secrets. It must not rewrite or
  polish the copy for submission.

## Show HN eligibility check

Project Loop Harness is a plausible Show HN candidate because it is public,
non-trivial, authored by the poster, and runnable locally without signup or an
email gate. A release announcement or article by itself is not a Show HN; the
submission should point to the runnable project rather than the Zenn article.

The human poster should decide whether this is the project's first substantive
Show HN. The Show HN rules say ordinary version upgrades are generally not
substantive enough.

## Facts the human may independently verify before writing

These are verification pointers, not suggested phrasing:

| Fact | Public source |
| --- | --- |
| Public source repository | https://github.com/mocchalera/project-loop-harness |
| Public release | https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0 |
| Published package | https://pypi.org/project/project-loop-harness/0.5.0/ |
| Python support | PyPI metadata says Python 3.10 or newer |
| Runtime dependencies | PyPI metadata declares no required runtime dependencies |
| First-use guidance | https://github.com/mocchalera/project-loop-harness/blob/main/docs/adoption-guide.md |
| Reproducible public-package demo | https://github.com/mocchalera/project-loop-harness/tree/main/examples/v0.5.0-adoption-demo |

Repository contracts to verify directly before making technical claims:

- SQLite is the current-state system of record.
- JSONL is an append-only audit projection.
- Generated HTML is a human review view, not machine state.
- Normal initialization has an inspect-first dry run.
- Core does not call an LLM and does not enable telemetry, cloud sync, provider
  execution, or automatic GitHub writes.
- Council is opt-in, experimental, and advisory; Direct remains the default.

## Manual authoring and submission checklist

- [ ] Write a new title from scratch; if using Show HN, begin it with
      `Show HN:`.
- [ ] Do not copy or paraphrase the abandoned AI-assisted HN draft.
- [ ] Link the submission to the public repository, not to a promotional article
      or landing page.
- [ ] Keep the title factual; avoid uppercase emphasis, exclamation points,
      superlatives, adoption claims, and gratuitous version framing.
- [ ] Disclose that the poster made and maintains the project.
- [ ] Make the project easy to try without signup.
- [ ] Do not ask anyone to upvote or comment.
- [ ] Be available to answer questions after posting.
- [ ] Obtain a fresh, explicit approval for the human-written title, target URL,
      timing, and any human-written first comment.

## Agent review boundary for human-written copy

After the human writes the candidate independently, an agent may return only a
fact-check report with locations and reasons, for example:

- verified public fact;
- unsupported or stale claim;
- URL failure;
- possible secret or private path;
- conflict with the HN rules.

The agent must not supply replacement wording, a rewritten title, a polished
paragraph, or an edited version intended for submission.
