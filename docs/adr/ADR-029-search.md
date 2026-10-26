# ADR-029: Search — PostgreSQL full-text and pg_trgm behind a search port; OpenSearch later

- **Status:** Accepted
- **Date:** 2026-10-26
- **Source:** WP-027; architecture.md §5 (search row), §6.5, §11.2; docs/specs/parity/01-work-items-incidents.md REQ-INC-085; D-052, D-068, D-085
- **Owner:** Haider (Product Owner)

## Context

architecture.md §5 names OpenSearch for full-text search and lists "PostgreSQL FTS (small
installs)" as the alternative. §6.5 has events update OpenSearch documents within seconds, with
permission filters applied at query time from the user's scope.

The first search requirement (REQ-INC-085, link and merge pickers) needs three things:
- every incident the user may see, exactly as the lists show them (D-052: groups, assignment, the
  unassigned queue of the user's sites; D-068: followers who kept access);
- display IDs, subject words, requester and status;
- Arabic and Urdu without diacritics, with word forms.

The product owner added typo tolerance and partial matches, and a port that stays ready for
meaning-based search (WP-038, similar incidents).

OpenSearch would mean the following at MVP:
- copying every scope fact (groups, sites, assignment, follows) into documents, and keeping them
  current when a membership or follow changes, or search leaks or hides records;
- a new stateful service in every profile: about 2 GB of memory on a single-node on-prem install,
  plus a backup target and a CI service;
- indexing lag, against §8 ("everything live");
- and still no Urdu stemmer, since OpenSearch ships none.

## Decision

1. **A search port** (`app/shared/search`). A module describes where its searchable text lives,
   using columns of its own table (`SearchDocument`). The engine returns a `Match`: a SQL predicate
   and a rank. The module adds them to the very query its list uses, after its own scope filter.
   Search can therefore never show a record the list would not. Permissions are not copied into
   an index (§11.2, one policy layer).
2. **The MVP engine is PostgreSQL** (D-085):
   - **Generated columns**: `search_vector` (tsvector) and a normalised short text
     (`search_subject`, `search_name`) on each searchable table. They are computed in the row's
     own transaction, so search is always current.
   - **Indexes**: GIN on the vector, and GIN `gin_trgm_ops` on the short text.
   - **One normalisation**, `sx_search_normalize`, applied to stored and typed text: NFKD, Arabic
     and Urdu diacritics, tatweel and zero-width characters dropped, case folded, and mixed-up
     letters unified (alef forms, yeh forms incl. Urdu ے and ی, kaf and keheh, heh forms incl.
     ہ, ھ and ة, Arabic-Indic and Urdu digits). Python mirrors it for typed text, and a database
     test proves both agree.
   - **Word matching**: every typed word must match. It matches as a prefix (`simple`), or by its
     English or Arabic stem (PostgreSQL's Snowball stemmers), or, for words of three letters or
     more, by trigram word similarity against the short text (≥ 0.5: "printr" finds "printer",
     "Mohamed" finds "Mohammed"). Urdu word forms match by prefix, since no Urdu stemmer exists.
   - **Ranking**: `ts_rank_cd`, plus trigram closeness. An exact display ID always comes first.
3. **People search** uses the same port on `users`: name and email words, with the email also
   split at its punctuation, plus name trigrams. It serves the people pickers (`GET /users?q=`),
   the assignee picker, and "incidents of requester …".
4. **OpenSearch stays the scale-out option.** It comes as another adapter behind the same port,
   when knowledge search, global search or facets need it (V1 or later). The adapter asks
   OpenSearch for candidate IDs and returns `id IN (…)` with their order as the rank, so the scope
   filter still runs in PostgreSQL.
5. **Meaning-based search** (WP-038): **pgvector in the same PostgreSQL is the preferred first
   option**. It is already installed (D-004). An embedding column per document, with a distance
   expression as predicate and rank, plugs into the same port, so permissions stay exact there
   too.

## Consequences

- **Positive:** search equals the lists by construction (tested per scope rule), with no index to
  rebuild, no lag and no new service.
- **Positive:** Arabic and Urdu are first-class. Arabic is stemmed; Urdu matches by prefix and
  letter variants.
- **Positive:** typos and partial words work for subjects and names.
- **Negative:** adding stored generated columns rewrites the table once (migration 0020). At large
  sizes, later changes to the indexed text need expand/contract with a backfill instead.
- **Negative:** GIN indexes are single-column (not tenant-first). Rows of other tenants that share
  a term are filtered by RLS and the tenant predicate after the index scan. That is fine at MVP
  sizes, and revisited (btree_gin or per-tenant partitioning) with the OpenSearch decision.
- **Negative:** a query mixing subject words and a person's name ("printer ahmed") matches only
  when all words are in one of them. Fields are not combined per word yet.
- **Neutral:** facets and highlighting are not in scope. They come with OpenSearch, or with
  PostgreSQL (ts_headline) when a screen needs them.

## Notes

`docs/architecture/search.md` describes how to make a new record type searchable.
