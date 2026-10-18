# BookRent Bot

A modern, production-grade Telegram bot for managing library book rental operations, built with Python 3.12, `python-telegram-bot`, PostgreSQL, SQLAlchemy 2.x ORM, and Alembic migrations.

---

## 📌 Implementation Status

### ✅ Completed: Phase 1 — Project Foundation
- Clean modular layout (`app/bot`, `app/database`, `app/services`, `app/scheduler`).
- Environment-driven Pydantic configuration with automatic secret redaction.
- SQLAlchemy 2.x ORM and PostgreSQL integration with connection pooling.
- Pre-flight database connectivity health check (`SELECT 1`).
- Structured logging with sensitive data masking filters.

### ✅ Completed: Phase 2 — Database Models & Inventory Foundations
- SQLAlchemy models: `Book`, `BookCopy`, `Customer`, `Rental`, `RentalExtension`, `CollateralLedger`, `AuditLog`.
- Canonical ISBN-10 and ISBN-13 normalization preventing duplicate book titles for ISBN variants.
- Physical hardcopy tracking with sequential barcode generation.
- Allowed inventory status transitions (`ON_SHELF`, `RESERVED`, `RENTED`, `OVERDUE`, `DAMAGED`, `LOST`).
- Financial collateral ledger tracking discrete transactions with fixed 2-decimal NUMERIC precision.

### ✅ Completed: Phase 3 — Telegram Registration, Cataloguing & Inventory
- Customer registration workflow through `/start` setting accounts to `PENDING`.
- Owner management console with `/pending`, `/approve <id>`, and `/reject <id>` workflows.
- Dual-layer authorization checks in both Telegram handlers and domain service functions.
- Owner book cataloguing via `/addbook` and stock receiving via `/receive`.
- Inventory inspection via `/inventory` (overall summary and individual copy inspection).
- Customer search and catalogue browsing via `/search` and `/books` restricted to `APPROVED` accounts.

### ✅ Completed: Phase 4 — Rental Requests, Owner Approval, Payments & Physical Checkout
- Customer rental requests via `/rent <book_id> [guarantee note]` with copy availability checks.
- Distinct request lifecycle (`SUBMITTED` -> `APPROVED` -> `COMPLETED`).
- Owner review with atomic copy reservation (`ON_SHELF` -> `RESERVED`) using `with_for_update()`.
- Separate financial accounting for rental fees, cash collateral deposits, and non-cash guarantees (IDs/passports).
- Dedicated due-date service implementing the **10-calendar-day end-of-day return convention** in configurable timezone (`RENTAL_TIMEZONE`).
- Owner-only physical handover confirmation activating the rental (`RESERVED` -> `RENTED`).
- Idempotency guards against duplicate callbacks and clicks.

### ✅ Completed: Phase 5 — Overdue Management, Extensions, Returns & Scheduling
- Daily overdue detection and charging (5.00 ETB/overdue day) backed by unique constraint `(rental_id, overdue_date)`.
- Independent customer and owner overdue Telegram notifications with delivery tracking.
- 5-calendar-day extension requests (`/extend`) with fixed 10.00 ETB fee and owner payment verification (`/approveext`).
- Owner-confirmed physical returns (`/return`, `/returndeduct`) recording condition notes, collateral deductions, and refunds.
- Financial reconciliation command (`/reconcile`) ensuring `Total Deposits = Deductions + Refunds + Net Balance`.
- Restart-safe scheduled overdue job running daily with automatic catch-up on missed days.

### ✅ Completed: Phase 6 — Production Readiness, Integration Testing & Deployment
- Live PostgreSQL integration test suite verifying table constraints, row locking, and transaction rollbacks.
- Alembic migrations (001, 002, 003) verified across both SQLite and live PostgreSQL (upgrade and downgrade).
- Guard against duplicate background scheduler registration in python-telegram-bot application runtime.
- PostgreSQL check constraints updated for all payment types (`EXTENSION_FEE`) and methods (`OTHER`).
- Complete backup and restoration runbook validated on live PostgreSQL using `pg_dump` and `psql`.
- Production deployment and environment configuration templates.

### ✅ Completed: Phase 7 — Telegram UX Improvement: Amharic/English, Navigation Buttons & Admin Clarity
- **First-Time Language Selection**: New users sending `/start` are presented with a clean language selection prompt (🇬🇧 English / 🇪🇹 አማርኛ) before accessing library services.
- **Persistent Language Preference**: Language preferences are saved in the `customers` table (`language` column) and remembered across sessions. Both customers and administrators can change their language anytime using the **Change Language / 🌐 ቋንቋ ቀይር** button or `/language` command.
- **Customer Navigation Reply Keyboard**: Full navigation menu with 7 actions available in English and Amharic:
  - 🔎 Search Books / መጻሕፍት ፈልግ
  - 📚 Browse Books / መጻሕፍትን ተመልከት
  - 📖 Request a Rental / የኪራይ ጥያቄ አቅርብ
  - 📋 My Rentals / ኪራዮቼ
  - ⏳ My Extensions / የማራዘሚያ ጥያቄዎቼ
  - 🌐 Change Language / ቋንቋ ቀይር
  - ❓ Help / እገዛ
- **Action Purpose Explanations**: Rich explanations of action purpose, duration, fees, and next steps after clicking any menu button (e.g., 5-day extensions for 10 ETB, 5 ETB/day overdue charges, owner approval requirements).
- **Status-Aware Guidance**: Clear explanations for `PENDING` accounts (awaiting owner approval) and `REJECTED` accounts (with stored rejection reason and owner contact instructions). Unapproved accounts pressing restricted buttons receive clear explanations why borrowing is not yet permitted.
- **Administrator Menu Reply Keyboard**: Complete 11-button menu removing the need to remember commands:
  - 👥 Pending Customers / በመጠባበቅ ላይ ያሉ ደንበኞች
  - 🚫 Rejected Customers / የተከለከሉ ደንበኞች
  - 📚 Manage Books & Stock / መጻሕፍትና ክምችት ማስተዳደር
  - 📝 Rental Requests / የኪራይ ጥያቄዎች
  - 💳 Payment Verification / የክፍያ ማረጋገጫ
  - ⏳ Extension Requests / የማራዘሚያ ጥያቄዎች
  - ⚠️ Overdue Rentals / ጊዜያቸው ያለፈባቸው
  - 📦 Confirm Returns / የመመለሻ ማረጋገጫ
  - 📊 Inventory Summary / የክምችት ማጠቃለያ
  - 🌐 Change Language / ቋንቋ ቀይር
  - ❓ Admin Help / የአስተዳዳሪ እገዛ
- **Rejected Customers Management & Reapproval**:
  - Visible **Rejected Customers / የተከለከሉ ደንበኞች** button and `/rejected` command.
  - Displays Customer ID, display name, @username, rejection timestamp, and stored rejection reason.
  - Page-by-page pagination (5 items per page) with Previous, Next, and Back to Admin Menu buttons.
  - Explicit **Reapprove Customer / ደንበኛ እንደገና አጽድቅ** action with owner authorization checks and audit logging (`REAPPROVE`).
- **Centralized Localization**: Dedicated translation dictionary and keyboard builders in `app/localization.py`.
- **Zero Regressions**: All 162 existing tests pass, plus 19 new automated tests covering all UX and localization flows (181 total passing tests).

### ✅ Completed: Phase 8 — Customer Verification & Event Notifications
- **Guided Multi-Step Registration**: Implemented multi-step conversation workflow using python-telegram-bot's `ConversationHandler`:
  - **Step 0 — Privacy Consent**: Detailed explanation of collected artifacts and collateral protection purpose with explicit agreement prompt (Policy v1.0).
  - **Step 1 — National ID Photo**: Image upload validated and stored securely via Telegram `file_id` (`national_id_file_id`).
  - **Step 2 — Phone Number**: Seamless one-tap contact sharing (`phone_verified=True`, `TELEGRAM_CONTACT`) or flexible manual entry with Ethiopian normalization (`+2519...`, `+2517...`) and international E.164.
  - **Step 3 — Residential Location**: One-tap GPS location coordinates (`latitude`, `longitude`) or readable text address.
  - **Step 4 — Confirmation Summary**: Formatted summary with masked phone numbers (`+251****4567`) and address/GPS details before submitting to owner.
  - **Navigation Controls**: Frictionless `⬅️ Back` and `❌ Cancel` at every step, plus `🔄 Restart` from summary.
- **Owner Verification & Secure Artifact Inspection**:
  - Enhanced `/pending` review cards display contact source (`TELEGRAM_CONTACT` vs `MANUAL`), residential location, and ID photo upload indicator.
  - Owner-only on-demand ID photo delivery via `view_id_photo:<customer_id>` inline callback. Non-owners are strictly rejected with an alert.
- **Centralized Localized Notification Service**:
  - `app/services/notification.py` handles localized alerts across 17 key library lifecycle events for both customers and owners.
  - Automatically queries recipient's preferred language (English or Amharic) from database, with English fallback.
  - Failure resilience: Telegram delivery failures are retried (configurable `NOTIFICATION_RETRY_ATTEMPTS`) and suppressed without rolling back database transactions.
  - Optional new book title broadcasts controlled via `ANNOUNCE_NEW_BOOKS`.
- **Database Evolution**:
  - Alembic migration `005_phase8_verification_and_notifications.py` applies all verification columns to PostgreSQL.
- **Comprehensive Testing & Zero Regressions**:
  - 204 passing automated tests across 21 test modules (23 dedicated tests in `tests/test_verification_and_notifications.py`).


---

## 📁 Project Structure

```
Book_rental_bot/
├── app/
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── bot.py             # PTB ApplicationBuilder and command router
│   │   └── handlers.py        # Customer & Owner command and callback handlers
│   ├── database/
│   │   ├── __init__.py        # Package exports
│   │   ├── base.py            # SQLAlchemy 2.x DeclarativeBase
│   │   ├── health.py          # Database health check and error sanitization
│   │   └── session.py         # Engine pooling and get_db_session context manager
│   ├── models/
│   │   ├── __init__.py        # Re-exports all models, enums, exceptions
│   │   ├── audit.py           # AuditLog model
│   │   ├── book.py            # Book and BookCopy models
│   │   ├── customer.py        # Customer model
│   │   ├── enums.py           # Domain status and transaction enums
│   │   ├── exceptions.py      # Domain custom exception hierarchy
│   │   ├── ledger.py          # CollateralLedger model
│   │   ├── overdue.py         # OverdueCharge and RentalExtension models
│   │   ├── rental.py          # Rental model
│   │   └── rental_request.py  # RentalRequest and Payment models
│   ├── scheduler/
│   │   ├── __init__.py        # Scheduler package exports
│   │   └── overdue_job.py     # Persistent daily overdue runner and job queue setup
│   ├── services/
│   │   ├── __init__.py        # Service layer exports
│   │   ├── audit.py           # Immutable audit log recorder
│   │   ├── book_catalog.py    # Title cataloguing, stock receiving, search
│   │   ├── customer.py        # Registration, verification, auth, approval workflows
│   │   ├── due_date.py        # 10-calendar-day return calculation & timezone service
│   │   ├── inventory.py       # Physical copy receiving and status transitions
│   │   ├── isbn.py            # ISBN validation and 13-digit canonical normalization
│   │   ├── ledger.py          # Financial ledger accounting and balances
│   │   ├── notification.py    # Localized event notifications, retries & failure suppression
│   │   ├── overdue.py         # Daily overdue detection, billing, and notifications
│   │   ├── rental.py          # Active rentals, extensions, and return confirmation
│   │   └── rental_request.py  # Rental request submission, approval, payments, checkout
│   ├── config.py              # Pydantic Settings schema, validation & timezone
│   ├── localization.py        # English/Amharic dictionaries and keyboard builders
│   ├── logging_config.py      # Sensitive data filtering and structured logging
│   └── main.py                # Application entry point & pre-flight runner
├── docs/
│   └── architecture.md        # Architecture blueprint, diagrams, and state machines
├── migrations/
│   ├── versions/
│   │   ├── 001_phase2_inventory_and_rental_models.py
│   │   ├── 002_phase4_rental_requests_and_payments.py
│   │   ├── 003_phase5_overdue_and_extensions.py
│   │   ├── 004_phase7_ux_localization_and_rejected_customers.py
│   │   └── 005_phase8_verification_and_notifications.py
│   ├── env.py                 # Dynamic Alembic environment
│   └── script.py.mako
├── tests/
│   ├── test_bot_handlers.py                   # Telegram bot Phase 3 handlers
│   ├── test_catalog_and_search_service.py     # Book cataloguing and search tests
│   ├── test_config.py                         # Configuration validation & secret masking
│   ├── test_customer_service.py               # Customer registration & auth tests
│   ├── test_database.py                       # Engine, session, and health check tests
│   ├── test_due_date.py                       # Due-date calculation & timezone tests
│   ├── test_inventory_service.py              # Physical copy status transition tests
│   ├── test_isbn.py                           # ISBN-10/13 normalization tests
│   ├── test_ledger_service.py                 # Collateral ledger accounting tests
│   ├── test_logging.py                        # Sensitive data masking tests
│   ├── test_migrations.py                     # Alembic upgrade/downgrade migration tests
│   ├── test_models.py                         # Model constraint & relationship tests
│   ├── test_overdue_service.py                # Overdue charges, extensions & return tests
│   ├── test_postgres_integration.py           # Live PostgreSQL integration & concurrency tests
│   ├── test_rental_concurrency.py             # Concurrent rental double-booking prevention
│   ├── test_rental_request_handlers.py        # Rental requests & payment handlers
│   ├── test_rental_request_service.py         # Request workflow & non-cash guarantees
│   ├── test_rental_service.py                 # Rental returns & extensions
│   ├── test_startup.py                        # Pre-flight startup & scheduler isolation
│   ├── test_ux_and_localization.py            # Phase 7 UX & bilingual navigation tests
│   └── test_verification_and_notifications.py # Phase 8 verification & notifications tests
├── .env.example               # Environment configuration template
├── alembic.ini                # Alembic configuration
├── requirements.txt           # Project dependencies
└── README.md                  # Project documentation
```

---

## 🔑 Environment Configuration

Create a `.env` file in the project root by copying `.env.example`:

```bash
cp .env.example .env
```

Configure the following variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather (`<bot_id>:<token>`) |
| `DATABASE_URL` | Yes | — | PostgreSQL URL (`postgresql+psycopg2://user:pass@host:5432/db`) |
| `APP_ENV` | No | `development` | Environment: `production`, `development`, or `testing` |
| `LOG_LEVEL` | No | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `ADMIN_USER_IDS` | No | `""` | Comma-separated Telegram User IDs with owner permissions |
| `RENTAL_TIMEZONE` | No | `UTC` | IANA timezone for rental deadlines (e.g. `Africa/Addis_Ababa`, `UTC`) |
| `OVERDUE_FEE_PER_DAY` | No | `5.00` | Overdue rate in ETB per calendar day |
| `EXTENSION_FEE` | No | `10.00` | Fixed 5-day rental extension fee in ETB |
| `EXTENSION_DURATION_DAYS`| No | `5` | Duration added per approved rental extension |
| `SCHEDULER_INTERVAL_HOURS`| No | `24` | Interval for automatic overdue charging job |

---

## 🤖 Available Bot Commands

### Customer Commands (Approved Accounts)
- `/start` — Register account or view registration status.
- `/books` — Browse all catalogued library titles.
- `/search <query>` — Search books by title, author, category, or ISBN.
- `/rent <book_id> [guarantee note]` — Submit a rental request for an available book.
- `/myrentals` — View personal active and past rentals.
- `/extend <rental_id>` — Request a 5-calendar-day extension (10.00 ETB fee).
- `/myextensions` — View status of personal extension requests.
- `/overdue` — View personal overdue rentals and accrued charges.
- `/help` — Display command reference.
- `/ping` — Check bot connectivity and responsiveness.

### Owner Administration Commands (Restricted to `ADMIN_USER_IDS`)
- **Customer Management**:
  - `/pending` — View pending customer registration queue.
  - `/approve <customer_id>` — Approve customer registration.
  - `/reject <customer_id> [reason]` — Reject customer registration.
- **Catalogue & Inventory**:
  - `/addbook <isbn> | <title> | <author> | <price> [| pages | category | desc]` — Catalogue a new title.
  - `/receive <isbn> <quantity>` — Receive physical hardcopies into inventory.
  - `/inventory [isbn_or_id]` — View overall inventory summary or inspect specific copy barcodes.
- **Rental Requests, Payments & Physical Checkout**:
  - `/requests [status]` — List active rental requests.
  - `/approvereq <request_id> [copy_id]` — Approve rental request and atomically reserve an `ON_SHELF` copy.
  - `/rejectreq <request_id> [reason]` — Reject rental request and release reserved copy back to `ON_SHELF`.
  - `/recordpayment <request_id> <fee|collateral> <cash|bank> <amount> [reference]` — Record manual verification of cash or bank transfer payment.
  - `/recordguarantee <request_id> <details>` — Record verified non-cash collateral guarantee (held ID or passport).
  - `/checkout <request_id>` — Confirm physical handover, activate `Rental`, and calculate 10-calendar-day return deadline.
- **Overdue, Extension & Return Processing (Phase 5)**:
  - `/checkoverdue` — Trigger an immediate on-demand run of the overdue detection and charging job.
  - `/extensions [status]` — List pending and processed rental extension requests.
  - `/approveext <ext_id> <cash|bank> [reference]` — Verify 10 ETB extension payment and extend return due date by 5 calendar days.
  - `/rejectext <ext_id> [reason]` — Reject rental extension request.
  - `/return <rental_id> [on_shelf|damaged|lost] [condition notes]` — Confirm physical return, inspect condition, and refund full collateral.
  - `/returndeduct <rental_id> <deduct_amount> <reason> [refund_amount]` — Confirm return with damage/overdue collateral deduction and refund remaining balance.
  - `/reconcile` — Execute financial integrity check reconciling deposits, deductions, refunds, and active balances across all accounts.

---

## 🗄️ Database Setup & Migrations

### 1. Create PostgreSQL Database
Connect to PostgreSQL as administrator:
```sql
CREATE USER bookrent_user WITH PASSWORD 'your_secure_password_here';
CREATE DATABASE bookrent_db OWNER bookrent_user;
```

### 2. Apply Migrations to Head
Run Alembic migrations using your configured database URL:
```bash
alembic upgrade head
```

### 3. Verify Current Migration Version
```bash
alembic current
```
Output should indicate `005_phase8 (head)`.

---

## 📢 Event Notification Matrix (Phase 8)

All business events dispatch bilingual (English / Amharic) notifications through the centralized `notification` service with failure suppression and automatic retries:

| Event Key | Trigger Context | Recipient | Localized English / Amharic |
|---|---|---|---|
| `notify_reg_submitted_admin` | Customer submits registration & ID artifacts | Library Owner(s) | 🔔 New customer registration with masked phone & location |
| `notify_customer_approved` | `/approve <id>` or inline button click | Customer | 🎉 Account approved & borrowing enabled |
| `notify_customer_rejected` | `/reject <id> [reason]` or inline button | Customer | ⚠️ Registration not approved with optional reason |
| `notify_req_submitted_admin` | `/rent <book_id>` request submitted | Library Owner(s) | 📝 New rental request with customer name & title |
| `notify_req_approved_cust` | `/approvereq <id>` request approved | Customer | ✅ Request approved, copy reserved, payment instructions |
| `notify_req_rejected_cust` | `/rejectreq <id> [reason]` request rejected | Customer | ❌ Request rejected with explanation |
| `notify_payment_recorded_cust`| `/recordpayment <id>` fee or deposit recorded | Customer | 💳 Payment receipt with amount, method, and reference |
| `notify_payment_recorded_admin`| Verified payment recorded | Library Owner(s) | 💳 Payment ledger audit notification |
| `notify_guarantee_recorded_cust`| `/recordguarantee <id>` non-cash guarantee | Customer | 📄 Document/ID guarantee verified (non-cash disclosure) |
| `notify_checkout_cust` | `/checkout <id>` physical book handover | Customer | 📖 Book checked out, return due date & penalty warning |
| `notify_ext_submitted_admin` | `/extend <rental_id>` 5-day extension requested | Library Owner(s) | ⏳ Extension request with customer details |
| `notify_ext_approved_cust` | `/approveext <id>` extension approved | Customer | ⏳ Extension approved, new due date confirmed |
| `notify_ext_rejected_cust` | `/rejectext <id> [reason]` extension rejected | Customer | ❌ Extension request rejected |
| `notify_return_cust` | `/return <rental_id>` full collateral refund | Customer | 📦 Return confirmed, complete deposit refund |
| `notify_return_deduct_cust` | `/returndeduct <rental_id>` collateral deduction | Customer | ⚠️ Return with deduction for damage/overdue fees |
| `notify_rental_due_today` | Scheduled job: rental due on current date | Customer | ⏳ Reminder: Rental return due today by 23:59 |
| `notify_rental_overdue` | Scheduled job: rental overdue | Customer | ⚠️ Overdue alert: 5.00 ETB/day accruing penalty |

---

## 🚀 Running the Bot

### Pre-flight Health Check
Verify configuration and database connectivity without starting the bot polling loop:
```bash
python -m app.main --check-only
```

### Start Application
```bash
python -m app.main
```
This runs pre-flight checks, initializes the Telegram Bot polling loop, and registers the daily background overdue detection scheduler.

To stop the bot, press `Ctrl+C`. The application shuts down gracefully.

---

## 🧪 Running the Complete Test Suite

Run the full pytest suite:
```powershell
pytest -v
```

### Actual Test Results (Verified)
```
====================== 204 passed, 2 warnings in 22.39s =======================
```

All 204 tests across all 21 test modules pass with 100% success rate:
- **Unit tests**: ISBN normalization, phone number normalization, due-date calculation, logging redaction, config validation.
- **Database & Model tests**: SQLAlchemy models, constraints, enums, exceptions, and sessions.
- **Service tests**: Customers, book catalogue, inventory, rental requests, payments, extensions, returns, overdue billing, ledger reconciliation, and event notifications.
- **Handler tests**: Telegram command, callback query, and multi-step conversation interactions with mocked contexts.
- **Concurrency tests**: Double-booking prevention via partial unique indexes.
- **Live PostgreSQL Integration tests**: Table schemas, row-level locking, duplicate billing prevention, non-cash guarantee isolation, transaction rollbacks, and full lifecycle execution.
- **Phase 8 Verification & Notification tests**: Complete guided registration conversation, navigation controls, sensitive data masking, owner-only National ID photo viewing, and notification failure resilience.

---

## 💾 Backup and Recovery Procedures

### 1. Creating a Database Backup
Use `pg_dump` to create a consistent SQL backup:
```bash
pg_dump -h localhost -U bookrent_user -d bookrent_db -f bookrent_backup_$(date +%Y%m%d).sql
```

### 2. Restoring from Backup
To restore to a new database (e.g., for recovery or staging verification):
```bash
createdb -h localhost -U postgres bookrent_restore_test
psql -h localhost -U postgres -d bookrent_restore_test -f bookrent_backup_YYYYMMDD.sql
```

### 3. Verifying Restored State
Check that Alembic recognizes the restored database at the head migration:
```bash
DATABASE_URL=postgresql+psycopg2://postgres@localhost:5432/bookrent_restore_test alembic current
```

---

## 🔒 Security Best Practices

1. **Never Hardcode Secrets**: All tokens, database credentials, and secret keys are loaded exclusively from `.env` or system environment variables.
2. **Automated Secret Redaction**: The Pydantic configuration and logging system automatically masks `TELEGRAM_BOT_TOKEN` and passwords in `DATABASE_URL` (e.g., `123456789:***REDACTED***`).
3. **Dual-Layer Authorization**: Owner commands verify staff authorization in both presentation handlers and domain services (`require_owner`).
4. **Parameterized Queries**: All database interactions use SQLAlchemy 2.x ORM or parameterized SQL, preventing SQL injection.
5. **Principle of Least Privilege**: In production, run the application using a dedicated PostgreSQL role granted only necessary DML permissions on the `bookrent_db` database.

---

## 📋 Verification & Operational Readiness Summary

| Component | Status | Verification Method |
|---|---|---|
| Configuration & Secret Redaction | ✅ Verified | Automated test suite (`test_config.py`) |
| SQLite Schema & In-Memory Tests | ✅ Verified | Automated test suite (156 SQLite tests) |
| PostgreSQL Schema & Migrations | ✅ Verified | Live PostgreSQL 18 instance with `alembic upgrade/downgrade` |
| PostgreSQL Row-Locking & Concurrency | ✅ Verified | Live PostgreSQL integration suite (`test_postgres_integration.py`) |
| Backup & Disaster Restore | ✅ Verified | Live `pg_dump` and `psql` restore cycle on PostgreSQL 18 |
| Telegram Handlers & Callbacks | ✅ Verified | Mocked Telegram context test suite (`test_bot_handlers.py`, `test_rental_request_handlers.py`) |
| Live Telegram Bot Polling | ⚠️ Unverified | Requires live Telegram Bot token from @BotFather in target production deployment |
| Single-Instance Polling Guard | ℹ️ Architecture Constraint | python-telegram-bot polling is designed for single active instances. Do not run multiple concurrent bot processes with the same token. |
