---
rfc: 0004
title: Build a local doc-scoped MCP server rather than adopting the official or community servers
status: Accepted
created: 2026-09-03
decided: 2026-09-04
supersedes:
superseded_by:
topic: server-ownership
commits: []
tags: [architecture, mcp, superhuman-docs]
---

# RFC 0004 — Build a local doc-scoped MCP server rather than adopting the official or community servers

## Context

The purpose of this repository is to let Claude and Claude Code work with one
specific Superhuman Docs document from inside a project folder. A project
directory is configured once, points at its own document, supplies its own
credentials through a local `.env`, and from then on every session in that
directory can read and edit that document.

RFC 0002 — since superseded by RFC 0008 — pinned the API surface and closed
with a question it deliberately did not answer:

> **Noted, not decided here.** The specification advertises an official
> Superhuman Docs MCP server. Whether that changes the case for building a local
> one is a separate question and, if pursued, a separate RFC.

That question is not rhetorical. The specification's own introduction recommends
the vendor's server over the raw API for AI integrations, describing it as
"optimized for LLM usage patterns" and noting it "often exposes more granular
methods for accessing and modifying data". Building a competing implementation
of something the vendor already ships, and ships better in places, needs a
reason beyond preference.

This session investigated the alternatives directly rather than reasoning from
the specification alone: reading the vendor's own MCP documentation and its
published tool list, reading the source of the leading community
implementation, and searching the vendor's developer forum for staff statements
about how these endpoints behave. The findings are recorded under `docs/` per
RFC 0003.

The requirement that decides the matter is narrow and worth stating precisely.
The server must be a **local process**, started by the MCP client, **pinned to a
single document**, configured **per project folder**, reading credentials from
**that folder's `.env`**, in a **Python and `uv`** toolchain. Each clause of that
sentence eliminates something.

## Decision

This repository builds its own MCP server: a local stdio process, written in
Python and managed with `uv`, scoped to a single Superhuman Docs document, and
installed per project folder.

The vendor's server is remote and workspace-scoped, which fails the local and
per-document requirements outright. The leading community server is local and
document-scoped and would otherwise serve, but it is a Node package and cannot
be pinned into a Python project the way this project requires.

Owning the implementation is not only a toolchain convenience. The underlying
page endpoints are more hazardous than a casual reading of their documentation
suggests: markdown is a lossy projection of a Superhuman Docs page, and the
vendor states these endpoints are "best used for import or export scenarios,
not page editing". A server that exposes them to a language model without
accounting for that risks silently destroying content, and existing
implementations do not account for it.

**How much is destroyed, and by which construct, is not yet measured.** The
severity rests on the vendor's own hedge plus desk research, not on observation;
`docs/validation/2026-09-03-markdown-fidelity-tests.md` was written to settle it
and has not been run. What is confirmed is the direction — images are omitted
from markdown export while HTML retains them, staff-confirmed — and that the
whole-page replace case is rated likely destructive and unconfirmed. The
argument for owning the code does not depend on the magnitude: an existing
server that ships the round trip with no warning at all is the problem
regardless of where the true severity lands.

Owning the code is what lets the tool surface encode those constraints, and that
surface is specified in RFC 0005.

Configuration and credential resolution are specified in RFC 0006. Packaging and
distribution are specified in RFC 0007.

## Alternatives considered

### Adopt the official Superhuman Docs MCP server

The vendor runs an MCP server and documents how to connect an AI client to it.
It is genuinely more capable than what this project will build. Its read tool
takes a `contentTypesToInclude` parameter spanning markdown, tables, formulas,
controls and comments — treating each as a separate channel rather than
flattening everything into markdown. It can annotate returned markdown with
`[[elementId]]` markers so that a model can address individual elements for
editing, and it offers table creation, which the v1 REST API does not expose at
all. Its editing model applies operations atomically with rollback.

It is rejected because of how it is deployed, not what it does. It is a hosted
service: a client connects to a server the vendor operates, and the user pastes a
document link into the conversation to say what to work on. There is no local
process, no per-project installation, no pinning to one document, and no reading
of a project-local `.env`. Every requirement in the Context section fails.

The vendor's connection documentation sits behind a bot challenge that could not
be read, so the exact authentication model is not established here. That gap does
not affect the decision — the deployment model alone is disqualifying — but it
should be closed before anyone revisits this.

### Adopt the community `coda-mcp` server

`orellazri/coda-mcp` is MIT-licensed, actively maintained, and close to the
target shape: a local stdio server, authenticated by an `API_KEY` environment
variable, scoped to a configured document, exposing roughly nineteen tools
covering pages and table rows. Run via `npx coda-mcp@latest` or a published
Docker image. Someone with the same goal and no Python constraint could
reasonably use it and be productive immediately, and this RFC should not be read
as a criticism of it.

It is rejected on two grounds. The first is runtime: it is Node and `npx`, and
this project pins a Python toolchain managed by `uv`, per-project and per-version
(RFC 0007). Carrying a Node dependency into every project folder to reach a
document defeats the point.

The second is that reading its source revealed defects that owning the code
avoids. Its page-export polling treats an HTTP 404 as fatal, when the vendor
documents 404 immediately after starting an export as an expected replication
delay to be retried. Its `duplicate_page` tool exports a page to markdown and
recreates it from that markdown, silently shipping the lossy round trip the
vendor warns against — a duplicated page can lose content the original had.
Neither its code nor its documentation carries any fidelity warning. These are
not reasons the project is bad; they are evidence that this API's hazards are
easy to miss, and that the value of this repository is largely in not missing
them.

### Wrap the official server as a thin local layer

Run the vendor's server as the engine and put a small local process in front of
it to pin the document and read the project `.env`. This would inherit the
vendor's superior tool design and leave far less code to maintain.

It is rejected because it inherits a remote dependency for what is meant to be a
local tool, adds a hop without removing one, and leaves the tool surface outside
this project's control — while still requiring a local process to be built and
distributed, which is most of the work. It also cannot be evaluated properly
until the vendor's authentication model is established.

### Mirror the REST API one tool per endpoint

Approximately twenty-five tools mapping mechanically onto the API's operations.
Simple to build, trivially complete, and easy to verify against the
specification.

Rejected because it is a surface built for an HTTP client rather than an agent.
Reading a page's markdown requires starting an asynchronous export, polling it,
and fetching a short-lived link; writes return immediately and must be polled
separately to learn whether they applied. Exposed one-to-one, the model must
orchestrate all of that itself, spending turns on mechanics, while
twenty-five near-identical tool descriptions crowd its context. Completeness here
costs quality.

### Expose the document as MCP resources plus a small action-tool set

Publish pages and tables as browsable MCP resources and offer perhaps six tools
for actions. Conceptually the most idiomatic use of the protocol and the cheapest
on context.

**Deferred rather than rejected.** Resource support varies across MCP clients in
a way tool support does not, and with the document already pinned to one ID the
indirection buys little for the initial version. It remains the natural direction
for a later revision, particularly for read-heavy use, and revisiting it would be
a new RFC rather than a reversal of this one.

### Shape tools around workflows rather than endpoints

The chosen approach: tools organised around what an agent is trying to
accomplish — twelve registered always and five more behind the destructive
flag — each absorbing an API mechanic the model should not have to
think about — pagination handled internally, asynchronous writes polled until
applied and any warning surfaced, markdown conversion hidden behind a single read.

Chosen because the same API surface, reorganised, is what separates a server that
technically works from one worth using — and because the mechanics being hidden
are exactly the ones that are dangerous to get wrong. The specific surface is
RFC 0005.

## Consequences

**Makes easy.** The server can be pinned per project folder at an explicit
version, alongside the document it serves and the credentials it uses. The tool
surface can encode the API's real hazards — lossy markdown, asynchronous writes
that cannot report failure, destructive whole-page replacement — instead of
passing them through to the model. Nothing depends on a remote service being
reachable.

**Makes hard.** Everything the community server would have provided free is now
ours to write and maintain: the HTTP client, retry and throttle policy, export
polling, mutation polling, column metadata caching, error translation. The
vendor's server will very likely stay ahead on capability, and some of what it
does — table creation, comments, atomic multi-operation rollback — is not
reachable from the v1 REST API at all, so this server cannot match it by
trying harder. That was read directly out of the served specification rather
than assumed: `info.version` 1.6.0 contains no path mentioning comments, no
operation that creates a table or a column, and no transaction or rollback
concept anywhere in its asynchronous write model. The inventory is recorded at
`docs/reference/api-operational-constants.md`.

**Commits us to.** Tracking API drift ourselves under RFC 0008, with no vendor
library absorbing the change. Carrying the maintenance of a client for an API
whose most important behaviours are documented in forum posts rather than in its
specification.

**Watch for.** If the vendor ships a locally-runnable or document-scoped version
of their server, the basis of this decision disappears and this RFC should be
superseded rather than defended. The same applies if a Python community
implementation reaches the quality bar this one is being built to.

## Implementation notes

Left empty at Proposed.
