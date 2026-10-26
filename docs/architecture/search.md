# Search

WP-027 · ADR-029 · D-085 · REQ-INC-085. Code: `backend/app/shared/search`.

## How it works

| Piece | Where | What it does |
|---|---|---|
| Normalisation | `domain.py` and SQL `sx_search_normalize(text)` (migration 0020) | NFKD; drops Arabic and Urdu diacritics, Latin accents, tatweel and zero-width characters; folds case; unifies mixed-up letters (alef, yeh incl. ی and ے, kaf and keheh, heh incl. ہ, ھ and ة) and Arabic-Indic and Urdu digits |
| Document | SQL `sx_search_vector(title, body)` | The title (weight A) and body (weight B) as `simple`, `english` and `arabic` lexemes |
| Port | `ports.py`: `SearchDocument`, `Match`, `TextSearch` | A module names its columns and gets back a predicate and a rank |
| Engine | `postgres.py`: `PostgresTextSearch` (`ENGINE`) | Every typed word must match: by prefix, by its English or Arabic stem, or (three letters or more) by trigram similarity of 0.5 or more |

Searchable today:

| Records | Columns (generated) | Indexes | Used by |
|---|---|---|---|
| Work items | `search_vector` (subject and description text), `search_subject` | `ix_wi_search_vector` (GIN), `ix_wi_search_subject` (GIN trigram) | `GET /incidents/search`, the command palette, `IncidentPicker` |
| Users | `search_vector` (name and email words), `search_name` | `ix_users_search_vector`, `ix_users_search_name` | `GET /users?q=`, user pickers, the assignee picker, "incidents of requester" |

Search columns are `unmapped_column`s: part of the table (so the migration check sees them), but
never loaded into or returned with the ORM object. Queries reach them through
`Model.__table__.c`.

## Permissions

Search starts from the module's own scope-filtered list query (for work items, `staff_rows`) and
adds the match to it. It can therefore never show more than the list. `tests/db/test_search_api.py`
checks the results equal the list for every visibility rule (D-052, D-068), for IDs too. RLS still
applies underneath.

## Making a new record type searchable

1. In a migration, add generated columns to the module's table:
   `search_vector tsvector GENERATED ALWAYS AS (sx_search_vector(<title>, <body text>)) STORED`
   and, for typo tolerance, `search_<short> text GENERATED ALWAYS AS (sx_search_normalize(<title>))
   STORED`. Add the GIN indexes (`gin_trgm_ops` for the short text).
2. Declare the same columns in the model with `unmapped_column(..., Computed(...))`.
3. In the service: `match = await ENGINE.match(session, SearchDocument(vector=..., short_text=...),
   text)`, then `scoped_query.where(match.predicate).order_by(match.rank.desc(), ...)`.
4. Test word forms in Arabic and Urdu, a typo, and that results equal the list for each scope rule.

Custom fields (WP-026) feed their free-text values into the work item body through
`sx_custom_text(custom)`.

## Languages

| Language | Word forms | Spelling variants |
|---|---|---|
| English | Snowball stemmer (`printers` → `printer`), plus prefixes | Accents dropped |
| Arabic | Snowball stemmer (`الطابعات`, `طابعة` → `طابع`), plus prefixes | Diacritics, hamza and alef forms, teh marbuta and heh, alef maksura and yeh |
| Urdu | Prefixes (`کمپیوٹر` finds `کمپیوٹروں`); no Urdu stemmer exists in PostgreSQL or OpenSearch | Urdu and Arabic kaf, yeh and heh typed either way, ے, digits |

## Limits and later

- A query mixing subject words and a person's name ("printer ahmed") matches only when all words
  are in one of them.
- No facets and no highlighting yet.
- OpenSearch (scale-out, facets, global search) comes as another adapter behind the same port
  (ADR-029 §4).
- Meaning-based search (WP-038) will use pgvector in the same database (ADR-029 §5).
- Adding stored generated columns rewrites the table once. Large tables need expand/contract with
  a backfill instead.
