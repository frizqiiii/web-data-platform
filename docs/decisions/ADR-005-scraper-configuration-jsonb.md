# ADR-005: Scraper Configuration as JSONB, Validated Per-Engine

## Context

`Scraper.configuration` needs to hold engine-specific settings
(timeout, concurrency, headers for HTTP; viewport/wait strategy for
browser automation; robots.txt policy for Scrapy) that differ
significantly across engines, and Phase 3 will add real engines this
schema needs to keep supporting without another migration.

## Decision

Store `configuration` as a single PostgreSQL `JSONB` column. Validate
it at the API boundary using a Pydantic discriminated union
(`app/schemas/scraper_configuration.py`) keyed on the `engine` field
— one schema class per engine (`HttpEngineConfig`,
`BrowserEngineConfig`, `ScrapyEngineConfig`), each with
`extra="forbid"`.

## Alternatives considered

- **Normalized columns** (one column per possible setting): rejected.
  Every new engine (Phase 3: Playwright, Scrapy) would need a schema
  migration, and most columns would be `NULL` for engines that don't
  use them — directly contradicts Section 6's requirement that engines
  be addable "without merusak domain model".
- **Untyped/unvalidated JSONB** (accept whatever the client sends):
  rejected — this is untrusted external input; without strict
  per-engine validation, a malicious or malformed `configuration`
  could carry unbounded values (huge `concurrency`, arbitrary headers)
  straight into whatever executes it in Phase 3.

## Trade-offs accepted

- Querying/filtering scrapers by a specific config field (e.g. "all
  scrapers with concurrency > 10") is harder than with normalized
  columns — not needed yet (no analytics feature exists), revisit if
  it becomes a real requirement.
- Schema evolution risk: if `HttpEngineConfig` gains a new required
  field later, existing stored JSONB rows won't retroactively have
  it. Mitigated only partially by the `version` integer on `Scraper`
  (a marker, not a migration mechanism) — a real fix (schema
  versioning/migration of stored JSONB) is out of scope for Phase 2
  and deferred to whichever future phase actually needs it.

## Consequences

- `app/schemas/scraper_configuration.py` is the single source of
  truth for what a valid configuration looks like per engine — Phase
  3's engine adapters must import and reuse these schemas (validate
  again at execution time) rather than re-implementing validation.
- Adding a 4th engine: one new Pydantic class + one new line in
  `default_configuration_for_engine` + one new value in the
  `ScraperEngine` enum + updating the migration's CheckConstraint
  (see ADR referenced in migration `0003`'s docstring) — no changes
  to `Scraper`, `Project`, or existing engine schemas.
