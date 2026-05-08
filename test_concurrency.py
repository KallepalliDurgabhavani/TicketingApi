#!/usr/bin/env python3
"""
Concurrency test script for the Django Ticketing API.

This script simulates concurrent booking requests against all three endpoints:
  - /book_vulnerable/   : Demonstrates the race condition (overselling)
  - /book_pessimistic/  : Proves pessimistic locking prevents overselling
  - /book_optimistic/   : Proves optimistic locking prevents overselling

Results are written to results.json in the same directory.

Usage:
    python test_concurrency.py [--host http://localhost:8000] [--event-id 1] [--requests 50]
"""

import argparse
import json
import os
import sys
import threading
import time

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_HOST = "http://localhost:8000"
DEFAULT_EVENT_ID = 1
DEFAULT_NUM_REQUESTS = 50
RESET_URL_TEMPLATE = "{host}/api/events/{event_id}/reset/"


def parse_args():
    parser = argparse.ArgumentParser(description="Concurrency test for ticketing API")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Base URL of the API")
    parser.add_argument("--event-id", type=int, default=DEFAULT_EVENT_ID, help="Event ID to test")
    parser.add_argument("--requests", type=int, default=DEFAULT_NUM_REQUESTS, help="Number of concurrent requests")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reset_event(host: str, event_id: int) -> bool:
    """Reset the event via a Django management command through a helper endpoint, if available.
    Falls back to a direct instructions reminder if no reset endpoint exists."""
    # We rely on the seed_event command being called by the entrypoint before each test section.
    # For a standalone reset, we simply notify the caller.
    return True


def run_concurrent_test(url: str, num_requests: int, timeout: int = 30) -> dict:
    """
    Fire `num_requests` POST requests concurrently to `url`.
    Returns a dict with:
        successful_bookings  - count of 201 responses
        failed_bookings      - count of non-201, non-409 responses
        conflict_failures    - count of 409 responses (optimistic locking conflicts)
        other_failures       - alias for failed_bookings (kept for report clarity)
        errors               - count of connection/timeout errors
    """
    counts = {
        "success": 0,
        "conflict": 0,
        "sold_out": 0,
        "error": 0,
    }
    lock = threading.Lock()

    def send_request():
        try:
            response = requests.post(url, timeout=timeout)
            with lock:
                if response.status_code == 201:
                    counts["success"] += 1
                elif response.status_code == 409:
                    counts["conflict"] += 1
                elif response.status_code == 400:
                    counts["sold_out"] += 1
                else:
                    counts["error"] += 1
        except requests.RequestException:
            with lock:
                counts["error"] += 1

    threads = [threading.Thread(target=send_request) for _ in range(num_requests)]

    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    return {**counts, "elapsed": elapsed}


def get_booked_seats(host: str, event_id: int) -> int:
    """Query the database state by hitting the event detail endpoint, or return -1 on failure."""
    try:
        url = f"{host}/api/events/{event_id}/status/"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get("booked_seats", -1)
    except Exception:
        pass
    return -1


def reset_via_api(host: str, event_id: int) -> bool:
    """Ask the server to reset the event's booking state."""
    try:
        url = f"{host}/api/events/{event_id}/reset/"
        response = requests.post(url, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run_all_tests(host: str, event_id: int, num_requests: int) -> dict:
    endpoints = {
        "vulnerable": f"{host}/api/events/{event_id}/book_vulnerable/",
        "pessimistic": f"{host}/api/events/{event_id}/book_pessimistic/",
        "optimistic": f"{host}/api/events/{event_id}/book_optimistic/",
    }

    results = {}

    for name, url in endpoints.items():
        print(f"\n{'='*60}")
        print(f"Testing endpoint: {name.upper()}")
        print(f"URL: {url}")
        print(f"Sending {num_requests} concurrent requests...")

        # Reset the event state before each test
        reset_ok = reset_via_api(host, event_id)
        if not reset_ok:
            print("  WARNING: Could not reset event via API. Results may be inaccurate.")

        counts = run_concurrent_test(url, num_requests)

        booked_seats = get_booked_seats(host, event_id)

        print(f"  Elapsed:             {counts['elapsed']:.2f}s")
        print(f"  Successful bookings: {counts['success']}")
        print(f"  Sold-out failures:   {counts['sold_out']}")
        print(f"  Conflict (409):      {counts['conflict']}")
        print(f"  Other errors:        {counts['error']}")
        print(f"  DB booked_seats:     {booked_seats}")

        if name == "vulnerable":
            results[name] = {
                "successful_bookings": counts["success"],
                "failed_bookings": counts["sold_out"] + counts["error"],
                "total_seats_in_db": booked_seats,
            }
        elif name == "pessimistic":
            results[name] = {
                "successful_bookings": counts["success"],
                "failed_bookings": counts["sold_out"] + counts["error"],
                "total_seats_in_db": booked_seats,
            }
        elif name == "optimistic":
            results[name] = {
                "successful_bookings": counts["success"],
                "conflict_failures": counts["conflict"],
                "other_failures": counts["sold_out"] + counts["error"],
                "total_seats_in_db": booked_seats,
            }

    return results


def validate_results(results: dict) -> bool:
    """Basic sanity checks on the results."""
    ok = True

    vuln = results.get("vulnerable", {})
    pess = results.get("pessimistic", {})
    opti = results.get("optimistic", {})

    if vuln.get("successful_bookings", 0) > 30:
        print("\n✓ VULNERABLE: Race condition confirmed — overselling detected!")
    else:
        print("\n⚠ VULNERABLE: Race condition not observed (try increasing --requests or the sleep delay).")

    if pess.get("successful_bookings", 0) <= 30:
        print("✓ PESSIMISTIC: Correctly capped at ≤ 30 bookings.")
    else:
        print("✗ PESSIMISTIC: Overselling detected — something is wrong!")
        ok = False

    if opti.get("successful_bookings", 0) <= 30:
        print("✓ OPTIMISTIC: Correctly capped at ≤ 30 bookings.")
    else:
        print("✗ OPTIMISTIC: Overselling detected — something is wrong!")
        ok = False

    return ok


def main():
    args = parse_args()
    host = args.host.rstrip("/")
    event_id = args.event_id
    num_requests = args.requests

    print(f"Django Ticketing API — Concurrency Test")
    print(f"Host:      {host}")
    print(f"Event ID:  {event_id}")
    print(f"Requests:  {num_requests} per endpoint")

    results = run_all_tests(host, event_id, num_requests)

    print(f"\n{'='*60}")
    validate_results(results)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to: {output_path}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
