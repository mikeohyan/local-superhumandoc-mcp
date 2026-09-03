---
rfc: NNNN
title: Short imperative phrase naming the decision
status: Proposed
created: YYYY-MM-DD
decided:
supersedes:
superseded_by:
commits: []
tags: []
---

# RFC NNNN — Short imperative phrase naming the decision

## Context

What forced this decision. The constraints in play, the problem that has no
obvious answer, and anything a reader six months from now would not already
know. Do not describe the solution here.

## Decision

The decision itself, in one or two paragraphs. Present tense, active voice:
"The server reads credentials from `.env`", not "The server will read" or
"We decided that credentials would be read". A reader should be able to stop
after this section and know what we do.

## Alternatives considered

### Option name

What it was, and why we did not take it. One short paragraph each. Rejected
options are the most valuable part of an RFC — they are what stops a future
session from re-proposing something already ruled out.

## Consequences

What this makes easy. What this makes hard. What it commits us to that would
be expensive to reverse. Be honest about the costs; an RFC with no downsides
listed is an RFC that has not been thought through.

## Implementation notes

Left empty at Proposed. Filled in by the session that ships the work: what was
actually built, anything that diverged from the Decision above and why, and the
commit SHAs recorded in the `commits` frontmatter field.
