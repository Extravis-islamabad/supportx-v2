# Database bootstrap SQL (single source of truth)

These files define the SupportX database roles, database grants and schema privileges. They are
run by **both**:

- the dev stack's PostgreSQL init (`deploy/compose/postgres/initdb/10-supportx.sh`, with `psql`), and
- `backend/tooling/db_bootstrap.py` (test fixtures and CI), which runs them through a tiny runner
  that understands the same psql syntax.

So the two can never drift. Only this psql subset is allowed here (the Python runner supports
exactly this):

- `:'name'` — a variable as a quoted literal; `:"name"` — a variable as a quoted identifier;
- statements end with `;` at the end of a line, or with `\gexec` (run the query, then execute each
  value it returns — used for conditional `CREATE ROLE` / `CREATE DATABASE`);
- full-line `--` comments.

| File | Connected to | Variables |
|---|---|---|
| `roles.sql` | any database (superuser) | `app_password`, `migrator_password`, `relay_password` |
| `database.sql` | `postgres` (superuser) | `database` |
| `schema.sql` | the new database (superuser) | — |
