# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: open the **Security** tab of this repository and choose **Report a vulnerability** (private security advisory). Do not open a public issue for a vulnerability.

Include what you found, how to reproduce it and the version or commit. This is a personal project maintained by one person, so there is no guaranteed response time, but reports are read.

## Scope and safety notes

- `planlens analyze` reads a JSON file and does not connect to a database. HTML output escapes everything taken from the plan.
- `planlens bench` and the hypopg adapter connect to a database. `bench` **creates and drops indexes** and runs `EXPLAIN ANALYZE`, which executes the query. It accepts only plain `CREATE INDEX` statements and read-only queries (data-modifying and locking keywords are rejected), but it cannot detect functions with side effects. Use a disposable database and a role with minimal rights.
- Connection strings can contain passwords. Pass them through environment variables or a secrets manager rather than shell history, and never commit them. The credentials in `docker-compose.yml` are placeholders for a throwaway local database.
- Suggested `CREATE INDEX CONCURRENTLY` statements are text for a person to review. The tool does not run them outside `bench`.

In scope: injection through plan or query files, unsafe handling of identifiers, secrets in output. Out of scope: running `bench` against a production database.
