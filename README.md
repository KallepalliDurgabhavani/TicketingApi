# Race-Condition-Proof Django Ticketing API

A Django REST API that demonstrates, proves, and fixes race conditions in a ticket booking system using:

- **Pessimistic locking** (`select_for_update`) — serialises access with a row-level database lock
- **Optimistic locking** (version-based compare-and-swap) — detects conflicts without holding locks
- **`transaction.on_commit`** — guarantees side effects (e.g. confirmation emails) only fire after a successful commit

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) ≥ 20
- [Docker Compose](https://docs.docker.com/compose/install/) ≥ 1.29
- Python 3.9+ (only needed to run `test_concurrency.py` locally)
- `requests` library (`pip install requests`)

---

## Quick Start

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd ticketing-api
cp .env.example .env   # edit values as needed
```

### 2. Start the stack

```bash
docker-compose up --build
```

This single command will:
1. Build the Django Docker image
2. Start a PostgreSQL container with a health check
3. Wait for the database to be ready
4. Run Django migrations automatically
5. Seed the database with a 30-seat event (`id=1`)
6. Start Gunicorn with 4 workers on port **8000**

The API is ready when you see:

```
web_1  | [INFO] Booting worker with pid: ...
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/events/{id}/book_vulnerable/` | ⚠️ Intentionally vulnerable (no locking) |
| `POST` | `/api/events/{id}/book_pessimistic/` | ✅ Safe — pessimistic locking |
| `POST` | `/api/events/{id}/book_pessimistic_fail/` | 🔬 Demonstrates `on_commit` rollback behaviour |
| `POST` | `/api/events/{id}/book_optimistic/` | ✅ Safe — optimistic locking |
| `GET`  | `/api/events/{id}/status/` | Returns current seat counts |
| `POST` | `/api/events/{id}/reset/` | Resets event state (used by test script) |

### Response examples

**Success (201)**
```json
{"status": "success"}
```

**No seats (400)**
```json
{"status": "error", "message": "No seats available"}
```

**Optimistic conflict (409)**
```json
{"status": "error", "message": "Conflict, please retry"}
```

---

## Running the Concurrency Tests

Make sure the application is running, then in a separate terminal:

```bash
python test_concurrency.py
```

The script fires **50 concurrent POST requests** at each of the three booking endpoints in sequence, resets the event between runs, and writes a `results.json` file summarising the outcomes.

### Expected results

| Endpoint | `successful_bookings` | Explanation |
|---|---|---|
| `vulnerable` | **> 30** | Race condition causes overselling |
| `pessimistic` | **≤ 30** | Lock serialises requests; exactly 30 succeed |
| `optimistic` | **≤ 30** | Version check prevents duplicates; extras get 409 |

### Optional arguments

```bash
python test_concurrency.py --host http://localhost:8000 --event-id 1 --requests 50
```

### results.json structure

```json
{
  "vulnerable": {
    "successful_bookings": 45,
    "failed_bookings": 5,
    "total_seats_in_db": 30
  },
  "pessimistic": {
    "successful_bookings": 30,
    "failed_bookings": 20,
    "total_seats_in_db": 30
  },
  "optimistic": {
    "successful_bookings": 30,
    "conflict_failures": 18,
    "other_failures": 2,
    "total_seats_in_db": 30
  }
}
```

---

## Verifying `on_commit` Behaviour

Send a request to the failing endpoint:

```bash
curl -X POST http://localhost:8000/api/events/1/book_pessimistic_fail/
# → 500 Internal Server Error
```

Check the container logs:

```bash
docker-compose logs web | grep CONFIRMATION
```

You should see **no output** — the `on_commit` hook was discarded when the transaction rolled back.

Then make a successful booking:

```bash
curl -X POST http://localhost:8000/api/events/1/book_pessimistic/
```

Check logs again:

```bash
docker-compose logs web | grep CONFIRMATION
# CONFIRMATION: Booking successful for event 1.
```

---

## Project Structure

```
ticketing-api/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── entrypoint.sh            # Runs migrations + seed + Gunicorn
├── requirements.txt
├── test_concurrency.py      # Concurrency test script
├── results.json             # Generated after test run
└── ticketing_project/
    ├── manage.py
    ├── ticketing_project/
    │   ├── settings.py
    │   ├── urls.py
    │   └── wsgi.py
    └── tickets/
        ├── models.py        # Event + Booking models
        ├── views.py         # All four booking endpoints
        ├── apps.py
        ├── migrations/
        └── management/
            └── commands/
                └── seed_event.py
```

---

## Key Concepts

### Race Condition (Read-Modify-Write)

The vulnerable endpoint reads `booked_seats`, checks availability in Python, then writes back — two concurrent requests can both pass the check before either writes, overselling seats.

### Pessimistic Locking

`Event.objects.select_for_update().get(id=...)` tells PostgreSQL to acquire an exclusive row lock. Concurrent requests queue behind the lock, making the check-and-update atomic.

### Optimistic Locking

No lock is held. Instead, the `UPDATE` statement includes `WHERE version = <read_version>`. If another transaction already incremented the version, `updated_rows == 0` and a 409 is returned. The caller must retry.

### `transaction.on_commit`

Callbacks registered with `transaction.on_commit()` run **only if the enclosing transaction commits**. A rolled-back transaction silently discards them, preventing phantom side effects.
"# TicketingApi" 
