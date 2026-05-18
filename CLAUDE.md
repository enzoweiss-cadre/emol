# eMolecules Analysis Project

## Supabase Project
Connected via MCP. See `.env` for credentials.

## Tables

### `emolecules_data_master`
- Raw query log data — **do not modify**
- ~50M rows, 7 columns: `query`, `qtype`, `ipaddress`, `qtime`, `qdatetime`, `web_site`, `emailaddress`
- Has an empty `session_count` column added (never populated — ignore it)
- Data spans 2020-01-01 to 2026-03-27
- NOTE: table has ~7GB of bloat from failed UPDATE attempts — autovacuum will clean over time

### `emolecules_data_by_email`
- One row per unique user email — 17,339 rows
- Columns: `emailaddress`, `query`, `qtype`, `ipaddress`, `qtime`, `qdatetime` (most recent), `web_site`, `session_count`, `domain`
- `session_count` = how many times that email appeared in the master table
- `domain` = extracted company domain from email (e.g. `gilead.com`)
- Linked to `emolecules_data_by_company` via `domain` column

### `emolecules_data_by_company`
- One row per company domain — 5,224 rows
- Columns: `domain`, `user_count`, `total_sessions`, `last_active`
- Excludes personal email domains (gmail, yahoo, outlook, etc.)
- Linked to `emolecules_data_by_email` via `domain` column

## Notable Findings
- `tdkob@vip.net.ru` has 44,157,857 sessions — 88% of the entire dataset, likely a bot/scraper
- Top companies by user count: Roche (544), Gilead (359), GSK (331), P&G (274), AstraZeneca (147)

## Disk Warning
- DB is ~14GB due to bloat from failed operations
- Supabase Pro limit is 8GB (overage billed at $0.125/GB)
- Avoid large in-place UPDATE operations on `emolecules_data_master` — the table has no indexes and limited temp disk
- Always work on the smaller derived tables (`by_email`, `by_company`) when possible
