# uv git-ref resolution — does a cached install actually miss new commits?

**Date:** 2026-09-08
**Target:** the mechanism the `packaging` topic gives for why a branch pin is
unsafe (see `_rfc/README.md`)

The `packaging` topic states that "uv caches on the fully-resolved commit
hash, so a branch pin does not pick up new commits without `--refresh`," and
concludes from that mechanism that a branch pin goes quietly stale. This file
records three observations made against a real `uv` install that contradict
the stated mechanism. Nothing here is authoritative for a decision — only an
RFC may say the project therefore pins one way or another. What that RFC
decided, and whether the decision itself still holds, is addressed in the
closing section; this file only reports what `uv` was seen to do.

## How to read the confidence markers

Reusing the scheme from `docs/reference/api-operational-constants.md` and
`docs/reference/mcp-client-environment.md`:

| Marker | Meaning |
|---|---|
| **[OBSERVED]** | Reproduced directly against a real `uv` install and a scratch git repository in this environment. |
| **[DOCUMENTED]** | Stated by `uv`'s own CLI help or output, not independently exercised beyond that. |
| **[CAVEAT]** | A limitation of the observation method itself — read before trusting the finding it's attached to. |

## Method

**uv version:** `0.11.6` (`uv --version`).

All three observations were made against a scratch package under git, using
`uvx --from "git+file://<path>@<ref>" <script>` — the same invocation shape
the `packaging` topic's own Distribution section documents, with a local
`file://` clone standing in for a real remote. For each observation the
sequence was: install once at a ref, mutate the scratch repository (add a
commit, or force-move a tag), then reinstall at the same ref **without**
`--refresh`, and check whether the reinstall resolved to the original commit
or the new one.

**[CAVEAT]** Every observation below used `git+file://` against a local
scratch clone. **`git+https://` against a real GitHub remote was not
tested.** This matters because the `packaging` topic's own Distribution
section, and this project's README, recommend the `git+https://` form for
actual installs — a `file://` clone and an HTTPS remote can differ in how uv
fetches, caches, or revalidates refs (a local filesystem read has no
transport-level caching to bypass, for instance), so nothing here is
established for the transport consumers actually use. Treat these findings as
evidence about uv's ref-resolution logic in principle, not as a claim already
verified for the shipped installation instructions.

## Results

### 1. A tag pin holds when the branch it once matched moves on

Installed `@v0.1.0`. A new commit was then added to `main`, with the `v0.1.0`
tag left untouched. Reinstalling `@v0.1.0`, without `--refresh`, resolved to
the **original** commit — the one the tag pointed at when it was created, not
the new tip of `main`. **[OBSERVED]** The pin held, exactly as intended.

### 2. A force-moved tag is picked up without `--refresh`

The `v0.1.0` tag was then force-moved to point at the newer commit from
observation 1. Reinstalling `@v0.1.0`, again without `--refresh`, picked up
the **new** commit and rebuilt against it. **[OBSERVED]** Nothing about the
reinstall command changed between this and the previous observation — only
what the tag pointed at on disk — so the different result isolates the tag
move as the cause.

### 3. A branch pin picks up new commits without `--refresh`

Installed `@main`. A new commit was added to `main`. Reinstalling `@main`,
without `--refresh`, picked up the **new** commit immediately. **[OBSERVED]**

This directly contradicts the `packaging` topic's stated mechanism. That
mechanism predicts the opposite outcome here: if uv cached on the
fully-resolved commit hash from the first `@main` install, a plain reinstall
with no `--refresh` should have kept resolving to the old, cached commit.
That is not what happened — the new commit was picked up right away.

## What is actually cached, versus what is not

Across all three observations, the built distribution artifact is cached by
its resolved commit hash — that much of the stated picture is correct. What
is not cached, or at least not in a way that survives to the next invocation,
is the **ref-to-commit resolution step itself**: `uv` appears to re-resolve
`@v0.1.0` and `@main` against the actual state of the repository on every
invocation, before consulting the artifact cache. A moved tag or an advanced
branch changes what that resolution step returns, which is why observations 2
and 3 both picked up new content without `--refresh` — the cache was never
asked about a stale answer, because resolution never handed it a stale
commit to look up in the first place.

## Which decision is affected, and which is not

**Not affected: the decision itself.** The `packaging` topic's rule — pin
tags, never branches — is unchanged by anything observed here, and nothing in
this file argues that it should change. If anything, observation 2 supports
the companion rule more directly than the topic's own reasoning did: "never
move a published tag" was justified by an appeal to caching (a moved tag
might be masked by a stale cached resolution and so go unnoticed); what was
actually observed is stronger and simpler — a moved tag is not masked at all,
it demonstrably and immediately reaches whoever reinstalls from it. A branch
pin remains the wrong choice for a released artifact, just not for the reason
originally given: the risk is not "a branch pin can go silently stale," it is
that a branch is not a stable identifier at all — anyone can push to it at
any time, tag or no tag, cache or no cache.

**Affected: only the stated reasoning.** The claim that "uv caches on the
fully-resolved commit hash, so a branch pin does not pick up new commits
without `--refresh`" describes a mechanism that was not observed here on uv
0.11.6. `--refresh` may still matter for other cases this file did not test —
for instance, forcing a redownload when the cache is suspected of holding a
corrupt or partial artifact for a commit that has not changed — but "make a
branch pin see new commits" is not a job `--refresh` needs to do, because
plain reinstallation already does it.

That RFC's body is frozen (it is Implemented), so this correction lives here
rather than being written into it; the frozen text keeps its original,
now-known-imprecise reasoning as a historical record, and this file is the
place a reader should be pointed to for the corrected mechanism.
