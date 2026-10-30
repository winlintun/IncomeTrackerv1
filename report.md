# Income Tracker — Full Audit Report

**Date:** 2026-10-30
**Scope:** `app.py`, `models.py`, `templates/index.html`, `templates/note.html`, `tests/test_app.py`, config/deploy files
**Method:** Static review + running the existing test suite + read-only database inspection + targeted API probes (SQLite sandboxes for probes)

---

## 🚨 P0 — READ THIS FIRST: running the test suite wipes the production database

This is not a theoretical risk. During this audit I ran the project's own test suite (`env/bin/python -m pytest tests/ -q`). The suite **connected to the configured Railway PostgreSQL database and dropped all of its tables**.

A read-only inspection immediately afterwards shows:

```
target host: ***REMOVED-HOST***/railway
tables: []
```

### Root cause (three bugs interacting)

1. **`app.py` connects and creates schema at import time** — `init_db_with_retry(app)` is called at module level (`app.py:89`), and it runs `db.create_all()` (`app.py:46`).
2. **Flask-SQLAlchemy binds the engine when `db.init_app(app)` runs** (`app.py:36`), before tests can change the URI.
3. **The test fixture changes the URI *after* import** (`tests/test_app.py:14`), which is too late. Verified:

```
engine URL in use: sqlite:////tmp/importA.db   # a later config change to fixtureB.db had no effect
A exists: True  B exists: False
```

So every fixture's `db.create_all()` / `db.drop_all()` (`tests/test_app.py:19-22`) ran against **production**. Because `.env` is loaded (`app.py:25`) and no `DATABASE_URL` is exported in the shell, the remote Railway URL was used. The 5m20s test runtime is the remote round-trip cost.

### Immediate actions (in order)

1. **Do not restart/redeploy the app yet.** A normal boot will `create_all()` empty tables, which can complicate restoring a dump.
2. **Check Railway backups / point-in-time recovery** (Railway Postgres service → Backups). This is the only way to recover data.
3. **Rotate the database password and `SECRET_KEY`** — the DB credentials are committed in plaintext (see S1 below), so they must be considered compromised.
4. **Fix the app/test bootstrap before running anything else** (see "Fix first" at the end).
5. **Add a guard in tests** that refuses to run if the engine URL is not the test database.

> Note: I cannot verify whether the database contained data before the test run. No local `backups/` directory or `.dump` file exists. If Railway backups are unavailable, the data may be unrecoverable.

---

## 🚨 P0-B — New account and data disappeared; next login said "Invalid credentials"

**Reported:** a new account was registered and data entered successfully, but the next login showed *"Invalid credentials. Please re-enter your password."* and the account/data were not in the database.

### What was verified

| Check | Result |
|---|---|
| Tables in the configured Postgres (`***REMOVED-HOST***/railway`) | all 7 existed |
| Rows in `job`, `income_record`, `expense`, `target`, `note` | **0** |
| Rows in `user` | only `(1, 'admin', 'admin')` |
| Local app process on port 3000 | none |
| Local SQLite files | only `pytest_income.sqlite`, used by tests |

The account was not in the database `.env` points to, so the write either went elsewhere or was erased.

### Root causes

1. **Silent ephemeral SQLite fallback.** `app.py` used `sqlite:///income_tracker.sqlite` whenever `DATABASE_URL` was unset. On Railway the container filesystem is ephemeral, so the account and rows disappear on the next restart/redeploy.
2. **No startup visibility.** Logs did not state which database the process actually used, and deployment variables could differ from the local `.env`.
3. **Misleading login message.** `templates/index.html` mapped **every** non-2xx login response (500, 502, timeout, proxy error) to "Invalid credentials", hiding the real server failure.
4. **Test database leakage.** The suite used a file SQLite database shared between tests; stale state caused false failures and made database-related regressions hard to trust.

### Fixes applied

| File | Change |
|---|---|
| `app.py` | `DATABASE_URL` is required outside development — missing/blank values raise `RuntimeError` instead of silently using SQLite. Development SQLite requires explicit `FLASK_ENV=development`/`APP_ENV=development`. |
| `app.py` | Startup logs the sanitized target (`dialect://host:port/database`, credentials removed). `pool_pre_ping` is enabled for Postgres; in-memory SQLite uses `StaticPool`. |
| `app.py` | New `GET /api/health/db` returns status, dialect, and sanitized target. |
| `templates/index.html` | "Invalid credentials" is shown only for HTTP 401; other statuses show `Login failed (HTTP n)`, and network failures show a connection error. Registration likewise handles network and non-JSON errors, and error text is escaped. |
| `tests/test_app.py` | The suite now uses in-memory `sqlite://`, drops/creates tables per test, and keeps the guard that refuses any non-test database. Added a health-endpoint test. |
| `pytest_income.sqlite` | Removed; tests no longer write a database file. |

**Verification:** `74 passed` with `env/bin/python -m pytest tests/ -q`. Starting with an empty `DATABASE_URL` now raises: `RuntimeError: DATABASE_URL is not set. Refusing to start outside development...`.

### Remaining action

These fixes prevent recurrence but cannot restore data already lost. Check Railway → Postgres → **Backups / point-in-time recovery**, and confirm the deployed service's `DATABASE_URL` points to the database you expect. If the account was written to an ephemeral container, it is unrecoverable.

---

## Severity legend

| Level | Meaning |
|---|---|
| **P0** | Data loss / production outage / credential compromise |
| **P1** | Security vulnerability, broken core flow, or guaranteed user-facing bug |
| **P2** | Important UX/performance/consistency issue |
| **P3** | Polish, maintainability, accessibility |

---

## 1. Security

### S1 — P0: Production database credentials committed in source

The same Railway connection string is hardcoded in two tracked files:

- `app.py:29` — default fallback `postgresql://postgres:<password>@***REMOVED-HOST***/railway`
- `railway_restore.py:19` — identical URL

Anyone with repository access can read and destroy the database. The password must be rotated now; deleting the lines later is not enough (git history retains them).

**Fix:** remove hardcoded URL, require `DATABASE_URL` and fail fast if missing; rotate credentials; purge history if the repo is public; use Railway secrets.

### S2 — P1: Store XSS (multiple injection points)

User-controlled values are interpolated into `innerHTML` without escaping. Verified that dangerous payloads are accepted:

- `POST /api/jobs` with `"name": "<img src=x onerror=alert(1)>"` → 201
- `"color": "red;\" onmouseover=\"alert(1)"` → 201 (injected into `style="background-color: ..."`)
- Usernames such as `<b>x</b>` → 201

Injection points (unescaped):

| What | Where |
|---|---|
| username | `index.html:558`, `1899`, `1901`, admin table |
| job name | `index.html:653`, `999`, `1410`, `1504`, `1760` |
| job color (style attr) | `index.html:985`, `987`, `1157`, `1189`, `1759` |
| job object in inline `onclick` | `index.html:991` (`JSON.stringify` inside an HTML attribute is entity-decoding–unsafe) |
| expense description | `index.html:2530`, `2575` |
| expense tags | `index.html:2437`, `2534`, `2641`, `2648` |
| expense type (unknown values) | `index.html:2390` |

The dedicated notes page escapes correctly (`note.html:767`), and embedded notes use `escH` (`index.html:2121`), but the rest of the SPA does not.

**Fix:** use `textContent` for text, an `escapeHtml` helper for every interpolation, `data-*` attributes + `addEventListener` instead of inline handlers, validate color as `#RRGGBB`, and add a strict CSP.

### S3 — P1: Cross-tenant job reference (authorization bypass)

`POST /api/income` looks up the job without checking ownership (`app.py:273`):

```python
job = db.session.get(Job, data['job_id'])
```

Verified: user **Bob** logged income against **Alice's** job and received `job_name: "AliceJob"` plus an auto-calculated amount of `7992` derived from Alice's private rate. The same flaw exists on update (`app.py:331`). This leaks another user's job name and pay rate and corrupts the income→job relation.

**Fix:** `Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()` in both places.

### S4 — P1: No CSRF protection; logout is a GET

All state-changing endpoints accept JSON without CSRF tokens, and `GET /api/auth/logout` (`app.py:182-186`) can be triggered cross-site. Session cookie flags are not configured (`Secure`, `SameSite`).

**Fix:** Flask-WTF CSRF (or double-submit token header), make logout POST, set `SESSION_COOKIE_HTTPONLY/SECURE/SAMESITE`.

### S5 — P1: Authentication endpoints fail open / 500 on malformed input

Verified:

| Request | Result |
|---|---|
| `POST /api/auth/register {}` | **500** (`KeyError: 'username'`) |
| `POST /api/auth/login {}` | **500** |
| register/login with 100-char password | **500** (`bcrypt` refuses >72 bytes) |
| login with 100-char password | **500** |

Registration has no minimum password length (only reset does, `app.py:165`), no username trimming/length validation, and first-user-admin is race-prone (`app.py:109`).

**Fix:** validate payloads up front, cap password bytes at 72, enforce length/username rules, catch `ValueError` from bcrypt, return 400.

### S6 — P1: User enumeration + no rate limiting

`/api/auth/forgot-password` returns `404 No account found with that username` (`app.py:135-136`), confirming account existence. Login and reset have no throttling, enabling brute force.

**Fix:** generic response for forgot-password, Flask-Limiter on login/forgot/reset, optional lockout/backoff.

### S7 — P1: Reset codes are printed to server logs; normal users cannot retrieve them

`app.py:144` prints the reset token with the username to stdout. The UI tells ordinary users to "check the Railway/production logs" (`index.html:441`), which they cannot do. This is both a credential-leak-to-logs issue and a broken recovery flow.

**Fix:** email the code (or use an admin-mediated flow); never log secrets.

### S8 — P2: Weak default secret key

`SECRET_KEY` falls back to `'dev-secret-key'` (`app.py:28`). If the env var is missing in production, sessions are forgeable.

### S9 — P2: API authentication returns 302 to a POST-only route

`login_manager.login_view = 'login'` (`app.py:39`) redirects unauthenticated API calls to `/api/auth/login`. Verified:

```
unauth GET /api/jobs  -> 302 Location: /api/auth/login?next=%2Fapi%2Fjobs
unauth GET /notes     -> 302 Location: /api/auth/login?next=%2Fnotes
```

That endpoint only accepts POST, so clients receive 405/HTML instead of 401 JSON. `note.html:711` checks for 401 and therefore never triggers. The SPA's `fetchData` then tries to parse an HTML error page.

**Fix:** `@login_manager.unauthorized_handler` returning JSON 401 for `/api/*` and a redirect to `/` for pages.

---

## 2. Data integrity & database

### D1 — P1: Deleting a job silently deletes the entire income history

`Job.income_records` uses `cascade="all, delete-orphan"` (`models.py:25`); `DELETE /api/jobs/<id>` (`app.py:262-264`) therefore removes all linked income records. Verified:

```
incomes before job delete: 1
job delete status: 200, incomes after: 0
```

The UI confirmation only says "Delete this job profile?" (`index.html:1099`), so users lose history without warning. Historical earnings also change retroactively.

**Fix:** soft-delete/archive jobs, or restrict deletion when income exists, or warn explicitly with a count.

### D2 — P1: Deleting a user fails on PostgreSQL (orphan foreign keys)

`User` has cascades for jobs/income/targets/expenses, but **not** for `Note` (`models.py:45-47`) or `PasswordResetToken` (`models.py:65-71`). Both have `user_id` FKs with no cascade. On PostgreSQL they raise a foreign-key violation; tests use SQLite where FK enforcement is off, hiding it. The admin "delete user" button (`app.py:427`) will 500 for any user who has a note or ever requested a reset.

**Fix:** add `ondelete='CASCADE'` and matching relationships, or delete dependent rows explicitly.

### D3 — P1: Invalid dates and negative amounts are accepted

Verified:

- `POST /api/expenses {date: "not-a-date"}` → **201**
- `POST /api/expenses {amount: -500}` → **201**

There is no validation on date format, month format, amount sign, NaN/Infinity, description length, tag length, or duplicate targets. Negative income/expenses corrupt all totals and charts; string months break sorting.

**Fix:** validate `YYYY-MM-DD`/`YYYY-MM`, require finite positive amounts (or explicitly allow negatives for refunds), enforce column lengths, add `UniqueConstraint(user_id, month)` on `Target`.

### D4 — P1: Money stored as floats

`Job.hourly_rate`, `IncomeRecord.amount`, `Target.amount`, `Expense.amount` are `Float` (`models.py:20,32,40,58`). Binary floating point cannot represent cents reliably; sums drift.

**Fix:** `Numeric(12, 2)`/`DECIMAL` with `Decimal`, or integer cents.

### D5 — P2: Manual schema migration in startup code

`init_db_with_retry` runs `create_all` and an ad-hoc `ALTER TABLE ... ADD COLUMN work_days_per_week` (`app.py:42-87`). Other schema changes are not handled, and every boot tries to create tables.

**Fix:** Flask-Migrate/Alembic; keep startup read-only.

### D6 — P2: Inconsistent/duplicate timestamps

`datetime.utcnow` (naive) is used for defaults (`models.py:24,34,42,51-52,62,71`), while notes set `datetime.now(timezone.utc)` (`app.py:524`). Columns are `timestamp without time zone`, so aware values are stored naive. Verified API output: `2026-10-29T16:39:19` with no `Z`/offset → frontend (local UTC+8) interprets it as local time, so a brand-new note displays **"8h ago"**.

**Fix:** store UTC-aware datetimes, serialize with `Z`, or send epoch milliseconds.

### D7 — P2: Password-reset tokens never cleaned up

Old/expired tokens accumulate; there is no cleanup task or index strategy beyond token.

---

## 3. Backend bugs & API consistency

| # | Issue | Evidence / Location |
|---|---|---|
| B1 | Missing required fields → **500** instead of 400 | `register`/`login` (`app.py:102,105,119`), `POST /api/income` without `job_id` (verified 500), `POST /api/targets` without `amount` (verified 500) |
| B2 | `TypeError` only partially handled | `PUT /api/expenses/<id>` with `amount: null` → verified **500** (`app.py:593-597`); job update catches only `ValueError` (`app.py:250`) |
| B3 | Legacy `User.query.get` | `app.py:95` (SQLAlchemy 2.x deprecation) |
| B4 | `datetime.utcnow` deprecated in Python 3.12+ | 59 warnings from the test suite (`app.py:139,169,627` and model defaults) |
| B5 | Status code inconsistency | `POST /api/targets` returns 200 on create (`app.py:376`, tests assert it) while jobs/income/notes/expenses return 201 |
| B6 | Inconsistent API errors | Flask's HTML 500/404 responses mixed with JSON; no global JSON error handler |
| B7 | `admin_stats` N+1 query + no scope | `r.user.username` lazy-loads per record (`app.py:454`); "total income" is all users (intended?) but should be documented |
| B8 | `expense_stats` loads everything and uses UTC month | Full table scan in Python (`app.py:626-646`); month from UTC (`app.py:627`) mismatches local-date records, especially near month boundaries; multi-tag expenses are counted in full under every tag |
| B9 | Unvalidated role values | `PUT /api/admin/users/<id>` accepts any string (`app.py:410-420`) |
| B10 | No target deletion endpoint | Users can only overwrite; no way to remove a target |
| B11 | No password-change endpoint for logged-in users | Only the forget/reset flow exists |
| B12 | No pagination/date filtering on list endpoints | `/api/income`, `/api/expenses`, `/api/notes` return everything |
| B13 | `IncomeRecord.job_name` is updated on PUT | Historical snapshot is silently rewritten (`app.py:332`) |
| B14 | `float(amount) == 0` means "auto" | A legitimate zero entry is impossible (`app.py:280-281`) |
| B15 | Registration is case-sensitive with no trim | ` alice` and `alice` are distinct; duplicates race |
| B16 | No `pool_pre_ping` | Long-idle Railway connections can 500 until reconnect |
| B17 | No health endpoint | Harder to verify deploy/DB readiness |
| B18 | `railway_restore.py` destructive restore has weak protection | Typed `yes` only; hardcoded credentials; no backup verification |

---

## 4. Frontend logic bugs

| # | Issue | Location |
|---|---|---|
| F1 | **Autosave race can corrupt note content.** `openNote` calls `saveNow()` then immediately reassigns `activeNote`; after the `await` resolves, `saveNow` writes the old note's data into the **new** `activeNote` and overwrites its history timestamp. Subsequent saves can persist the wrong content. | `note.html:771-772` + `829-849`; embedded duplicate `index.html:2208-2209` + `2186-2206` |
| F2 | **Unsaved edits can be lost on tab close.** `beforeunload` calls an async `fetch` that the browser may cancel. | `note.html:938-940` |
| F3 | Timezone display bug (see D6): "just now" shows "8h ago" in UTC+8. | `note.html:717-731,2110-2119` |
| F4 | Save-error color persists: `setSaveIndicator` resets `className` but not `style.color`. | `note.html:903-909`; `index.html:2147-2155` |
| F5 | "Daily Average" divides by **today's** date even when viewing another month; caption also says "today". | `index.html:836,839`; expenses `2354` |
| F6 | With no target set (`target = 0`), any income shows "Target Achieved!" and "Exceeded Target by", because `monthlyIncome >= target` and `monthlyIncome > target`. | `index.html:802-811`; targets view `1611` |
| F7 | Weekly charts always show the last 7 days from today, ignoring `selectedMonth`. | `index.html:750-760`; expenses `2319-2325` |
| F8 | Income "Records" list and expense list are not filtered by the selected month, unlike the cards/charts. | `index.html:1184`, `2442` |
| F9 | "Set Target" modal defaults to the **current** month, not the month being viewed. | `index.html:1683` |
| F10 | Work-pace panel always computes for the current month even when another month is selected; `saveWorkDays` also always writes the current month. | `index.html:1240-1258`, `1367-1377` |
| F11 | Unknown `?view=` renders a blank page; `?view=admin` as a non-admin causes `stats.total_users` on an error object and a blank/crashed view. No `res.ok` checks in `renderAdmin`. | `index.html:173-177`, `1838-1845` |
| F12 | `init()` has no try/catch; a network failure leaves the loading spinner forever. | `index.html:168-181` |
| F13 | `fetchData()` calls `.json()` without checking `res.ok`; expired sessions yield parse errors. | `index.html:183-194` |
| F14 | Global state mutated during render via in-place `.sort()`. | `index.html:1184`, `1635`, `2521` |
| F15 | Double submit possible: buttons are never disabled while a request runs. | all forms |
| F16 | `document.querySelector('.fixed')` closes an arbitrary fixed element. | `index.html:689`, `1448`, `1535` |
| F17 | Inconsistent confirmations: native `confirm/alert` for jobs/income/expenses/users vs custom modal for notes. | `1099`, `1465?` etc. |
| F18 | No URL routing: `?view=` is read once then erased; back/forward and deep links are broken. | `index.html:173-177` (also in `docs/ux-review.md`) |
| F19 | Notes exist twice: embedded SPA version (`index.html:1977-2280`) and standalone `/notes` (`note.html`), with different markup/CSS and duplicated logic. | — |
| F20 | Register success uses `alert()` while the rest of the app uses toasts. | `index.html:361` |
| F21 | `updateDateColor` colors a border green permanently with no reset. | `index.html:1476-1479` |

---

## 5. UI / UX issues (yes, UI needs changes)

1. **Font is never applied.** `font-family: 'Plus+Jakarta+Sans'` (`index.html:21`) is the URL-encoded form; the CSS family name must be `'Plus Jakarta Sans'`. The font loads but the page falls back to `sans-serif`.
2. **Dark mode is incomplete.** Only a subset of utilities is remapped (`index.html:57-98`). Examples that break: `focus:bg-white` (inputs turn white on focus while text is near-white), `shadow-zinc-200` (light shadows), `hover:bg-white`, `bg-emerald-*`/`text-emerald-*` combinations, chart tick colors (expense charts pass no colors at all). The dedicated notes page is permanently dark with no toggle, while the main app defaults to light.
3. **Edit/delete affordances are hover-only** (`index.html:1197`, `2541`) — invisible and unusable on touch devices. Income edit/delete and expense delete cannot be used on mobile.
4. **Calendar details are hover-only** (`index.html:1161`) — no details on touch.
5. **No empty states**: Jobs, Income, Expenses, Targets, and all charts render blank grids/canvases with no guidance. (Also flagged in `docs/ux-review.md`.)
6. **No loading states**: Admin view stays empty until fetches finish; forms give no progress feedback.
7. **Forgot-password flow is unusable for non-admins** (reset code only in server logs) and user enumeration is exposed (`app.py:135-148`).
8. **Target of 0 reads as "achieved"** (F6) — misleading.
9. **Month context is inconsistent**: cards/calendars use `selectedMonth`, records/expense lists and weekly charts don't (F7-F10).
10. **Mobile layout**: calendar uses `p-10` + `grid gap-4` in 7 columns, making cells cramped on small screens; the notes page combines `overflow:hidden` on `html/body`, a 100vh editor, and a top nav, which can clip content (`note.html:33,296`).
11. **Accessibility gaps**:
    - Calendar days are clickable `<div>`s with no keyboard access or roles (`index.html:1156`).
    - Icon-only buttons lack `aria-label`.
    - Modals lack `role="dialog"`, focus trap, focus restore, and Escape handling.
    - `<label>` elements are not associated with inputs via `for`/`id`.
    - Toasts are not `aria-live`.
    - Large amounts of 10px `text-zinc-400` on white fail contrast requirements.
    - Native `confirm()` is inaccessible/inconsistent.
12. **Number formatting**: no fixed decimals for fractional amounts; currency hardcoded to NTD.
13. **No undo** for deletes; several deletes are one click with no recovery.
14. **Two Tailwind versions loaded** (see P7) can cause subtle style conflicts and flashes.

---

## 6. Performance (yes, performance needs changes)

### P1 — P0/P1: Import-time remote DB connection and schema creation
`app.py:89` connects at import with 5 retries × 3s. Consequences:
- Test suite takes **320 seconds** for 60 tests (mostly remote DB round trips).
- Gunicorn workers block at boot if the DB is slow/unavailable; Railway health checks may time out.
- Any CLI import (`flask shell`, scripts, tests) touches production.

**Fix:** app factory + `flask db upgrade`; never connect at import.

### P2 — Duplicate/large frontend dependencies
- Two Tailwind engines loaded: `cdn.tailwindcss.com` (v3 Play CDN) and `@tailwindcss/browser@4` (`index.html:7-8`). Both compile at runtime in the browser; v4 browser build is explicitly not for production.
- `unpkg.com/lucide@latest` and `chart.js` unpinned, no SRI (`index.html:9-10`) — slow, cache-unfriendly, supply-chain risk.

**Fix:** compile Tailwind once at build time; self-host/pin versions with SRI; load non-critical scripts with `defer`.

### P3 — Charts are recreated on every render and never destroyed
`new Chart(...)` is called after every full re-render (`index.html:891,931,1654,2463,2490,1804`). Old canvas elements are removed but chart instances/listeners are not destroyed, leaking memory across view/month/theme changes.

**Fix:** keep chart refs, call `destroy()` before re-render, or update `chart.data` in place.

### P4 — Full-app re-render on every state change
`render()` rebuilds the entire nav and view via `innerHTML` for month navigation, theme toggle, menu open, etc., then reruns `lucide.createIcons()` and re-fetches admin data. This discards scroll position, focus, and animations.

**Fix:** render only the affected subtree; use event delegation.

### P5 — Unbounded data + repeated O(n×jobs) scans
`GET /api/income` and `/api/expenses` return all rows. Every view re-filters and re-sums them repeatedly (dashboard per job, jobs per card, summary per job, charts). Renders are O(records × jobs). No pagination or date-range queries.

**Fix:** server-side `?month=YYYY-MM` and aggregates; paginate lists; add composite indexes `(user_id, date)` on `IncomeRecord`/`Expense`, `(user_id, month)` on `Target`, `(user_id, updated_at)` on `Note`.

### P6 — DB engine lacks resilience settings
No `pool_pre_ping`, no pool tuning. Railway/Postgres idle disconnects can surface as intermittent 500s.

### P7 — `expense_stats` and `admin_stats` are not SQL aggregates
`expense_stats` loads all expenses and aggregates in Python (`app.py:626-646`); `admin_stats` triggers N+1 lazy loads. Use `func.sum`/`group_by`.

### P8 — `create_all` + information_schema introspection on every boot
`app.py:42-87` runs multiple catalog queries on every worker start. With 2 workers this is duplicated; use migrations.

---

## 7. Configuration, deployment, and documentation

| # | Issue |
|---|---|
| C1 | **Python version mismatch:** `runtime.txt` = `python-3.11.x`, `pyproject.toml` = `==3.12.1`, `mise.toml` = `3.12.1`, `app.py` script header = `>=3.13`. Pick one and align all files. |
| C2 | The `app.py` inline script metadata pins `flask-bcrypt==1.0.1` etc., duplicating `requirements.txt`; it can drift (it already does conceptually). |
| C3 | `.env` on disk points at the production database, so local dev/tests target production. Use `.env.example` with SQLite and require explicit opt-in for remote. |
| C4 | `requirements.txt` includes `pytest` in the production image (bloat; minor). |
| C5 | `README.md` is stale: it references a `Transaction` model, says `models.py` has `(User and Transaction)`, and omits Notes/Expenses/Password reset. |
| C6 | `AGENTS.md` instructs `datetime.utcnow`, which is deprecated and conflicts with newer code; it also omits expenses/notes/reset behavior. |
| C7 | No logging configuration; sensitive reset tokens are printed (`app.py:144`). |
| C8 | No health endpoint, no error monitoring (Sentry), no request IDs. |
| C9 | `railway_restore.py` hardcodes credentials and offers a destructive restore without a safety backup. |
| C10 | No `Content-Security-Policy`/security headers; no HSTS behind TLS. |

---

## 8. Testing gaps

The suite currently **passes 60/60 while wiping the production database** — a false sense of safety.

1. Tests never exercise PostgreSQL-specific behavior (FK cascades, timezone columns), which is why D2 and D6 are invisible.
2. The fixture's DB override is ineffective (`tests/test_app.py:14`). No assertion that the engine is actually the test DB.
3. No tests for:
   - cross-user job_id references (S3),
   - invalid/missing payloads (S5, D3),
   - negative/zero/NaN amounts,
   - job deletion → income history,
   - deleting users with notes/reset tokens,
   - XSS payload handling,
   - timezone serialization,
   - rate limiting/CSRF,
   - frontend logic (F1-F21).
4. Tests mutate production schema on import (`db.create_all`), before the fixture even runs.
5. No frontend/e2e tests at all; the notes autosave race and mobile hover-only controls cannot be caught by the API suite.

**Fix:** app factory, explicit test config applied before `db.init_app`, a hard guard:

```python
if "postgresql" in str(db.engine.url):
    raise RuntimeError("Refusing to run tests against PostgreSQL")
```

Use pytest-postgresql or a disposable database for PG-specific tests, and Playwright for the critical UI flows.

---

## 9. What is working well

- ORM usage is parameterized — no SQL injection found in user-facing queries.
- Per-user filtering is correct on jobs/income items/targets/notes/expenses (except the job reference in S3).
- Single-admin enforcement is tested; last-admin protections exist.
- Password reset tokens are single-use and expiring; passwords are bcrypt-hashed.
- The dedicated notes page escapes HTML correctly and has a working autosave (apart from the race).
- Core CRUD for income/expenses/jobs/notes works; 60 API tests pass.
- Dark-mode chart colors and the work-pace UI receive careful attention — the foundation is good.

---

## 10. Recommended work order

### Phase 0 — Containment (today)
1. Rotate DB password + `SECRET_KEY`; remove hardcoded credentials from `app.py` and `railway_restore.py`.
2. Attempt Railway backup/PITR restore; pause deploys.
3. Fix test bootstrap so it can never touch production:
   - Extract `create_app(config)`; move `init_db_with_retry` behind `if __name__ == '__main__'` or a CLI command.
   - `db.init_app` only after test config is applied.
   - Add the PostgreSQL guard in the test fixture.
4. Add `.env` safety: default to SQLite locally; require an explicit remote flag.

### Phase 1 — Security & correctness
5. Fix S3 ownership checks; add authorization tests.
6. Add input validation (dates, months, finite positive amounts, lengths) and a global JSON error handler (fixes B1, B2, D3).
7. Escape all interpolations / remove inline handlers; validate colors; add CSP (S2).
8. CSRF + secure cookies + logout POST; rate-limit auth; generic forgot-password response (S4-S6).
9. Add DB cascades for notes/reset tokens (D2); protect job deletion from silent history loss (D1).
10. Switch money to `Numeric`/cents (D4); add composite indexes (P5).
11. Fix timezone storage/serialization (D6/F3).

### Phase 2 — Frontend correctness
12. Fix the note autosave race (capture note id/content before await) and unload saving (`keepalive`/`sendBeacon`) (F1, F2).
13. Fix dashboard month math, target=0, weekly chart scope, records-list filtering, target modal month, work-pace scope (F5-F10).
14. Add error handling/loading/empty states; disable submit buttons in-flight (F11-F15).
15. Make edit/delete controls always visible on touch; add keyboard-accessible calendar and modals; aria labels/live regions (UI 3-5, 11).

### Phase 3 — Performance & polish
16. Single precompiled Tailwind, pinned/self-hosted deps with SRI (P2).
17. Chart lifecycle management and subtree rendering (P3, P4).
18. Server-side month filtering + aggregates + pagination (P5, P7).
19. Flask-Migrate, `pool_pre_ping`, health check, logging/monitoring (D5, P6, P8, C7-C9).
20. Align runtime versions and update README/AGENTS (C1, C5, C6).
21. Consolidate the two notes implementations and the two design systems (F19, UI 2).

---

## 11. Evidence summary

Commands used and key observations:

| Check | Result |
|---|---|
| `pytest tests/ -q` | 60 passed in **320.59s**; 59 deprecation warnings |
| Engine override probe | Later `SQLALCHEMY_DATABASE_URI` change ignored; engine stayed on import-time URL |
| DB inspection after tests | `tables: []` on `***REMOVED-HOST***/railway` |
| Unauthenticated `/api/jobs` | 302 → `/api/auth/login?next=/api/jobs` (POST-only) |
| Bob → Alice's job income | 201, leaked `AliceJob`, auto-calculated `7992` |
| Register/login `{}` | 500 (`KeyError`) |
| 100-char password login | 500 (bcrypt >72 bytes) |
| Negative expense | 201 (`amount: -500`) |
| Invalid date | 201 (`date: "not-a-date"`) |
| Target `amount: "abc"` | 500 |
| Expense `PUT {amount: null}` | 500 |
| Job delete with income | 200; income count 1 → 0 |
| XSS job name / color / username | 201 (stored unescaped) |
| Note timestamps | `2026-10-29T16:39:19` (no offset), local time was 00:39 → renders "8h ago" |

---

*Report generated from static analysis, runtime probes, and the existing test suite. No data was intentionally modified; however, running the suite triggered the P0 database-drop bug described at the top.*
