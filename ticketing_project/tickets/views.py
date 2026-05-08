import logging
import time

from django.db import models, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .models import Booking, Event

logger = logging.getLogger('tickets')


def send_confirmation_email(event_id):
    """
    Simulated email confirmation. In production, this would dispatch to
    an email service or a task queue (e.g., Celery).
    This function is registered via transaction.on_commit() and will ONLY
    execute if the surrounding transaction commits successfully.
    """
    print(f"CONFIRMATION: Booking successful for event {event_id}.", flush=True)
    logger.info(f"CONFIRMATION: Booking successful for event {event_id}.")


@csrf_exempt
@require_POST
def book_vulnerable(request, event_id):
    """
    VULNERABLE endpoint - intentionally susceptible to race conditions.

    Uses the classic read-modify-write anti-pattern:
    1. Read: Fetch the event from the database.
    2. Check: Evaluate booked_seats < total_seats in Python memory.
    3. Sleep: Artificial delay widens the race window for testing.
    4. Write: Save incremented count back to the database.

    Two concurrent requests can both pass the check before either writes,
    resulting in overselling.
    """
    try:
        event = Event.objects.get(id=event_id)

        if event.booked_seats < event.total_seats:
            # Artificial delay to widen the race window for demonstration
            time.sleep(0.1)
            event.booked_seats += 1
            Booking.objects.create(event=event, user_name='Test User')
            event.save()
            return JsonResponse({'status': 'success'}, status=201)
        else:
            return JsonResponse(
                {'status': 'error', 'message': 'No seats available'},
                status=400
            )
    except Event.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Event not found'},
            status=404
        )


@csrf_exempt
@require_POST
def book_pessimistic(request, event_id):
    """
    SAFE endpoint using Pessimistic Locking.

    Uses transaction.atomic() combined with select_for_update() to acquire
    an exclusive row-level lock on the Event. Any concurrent request that
    tries to lock the same row will block until this transaction completes.

    transaction.on_commit() ensures the confirmation callback is only
    triggered if the transaction successfully commits.
    """
    try:
        with transaction.atomic():
            # Acquire an exclusive row-level lock on this event.
            # Concurrent requests will queue here until this transaction ends.
            event = Event.objects.select_for_update().get(id=event_id)

            if event.booked_seats < event.total_seats:
                event.booked_seats += 1
                Booking.objects.create(event=event, user_name='Test User')
                event.save()

                # Register side effect to run ONLY after successful commit.
                # If any exception occurs before commit, this will NOT run.
                transaction.on_commit(lambda: send_confirmation_email(event_id))

                return JsonResponse({'status': 'success'}, status=201)
            else:
                return JsonResponse(
                    {'status': 'error', 'message': 'No seats available'},
                    status=400
                )
    except Event.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Event not found'},
            status=404
        )
    except Exception as e:
        logger.error(f"Unexpected error in book_pessimistic: {e}")
        return JsonResponse(
            {'status': 'error', 'message': 'Internal server error'},
            status=500
        )


@csrf_exempt
@require_POST
def book_pessimistic_fail(request, event_id):
    """
    Demonstrates that transaction.on_commit() does NOT fire on rollback.

    This endpoint is identical to book_pessimistic but deliberately raises
    an exception after the booking logic, causing the transaction to roll back.
    The on_commit callback is registered but must NOT execute.
    """
    try:
        with transaction.atomic():
            event = Event.objects.select_for_update().get(id=event_id)

            if event.booked_seats < event.total_seats:
                event.booked_seats += 1
                Booking.objects.create(event=event, user_name='Test User')
                event.save()

                # Register the same on_commit hook as the working endpoint
                transaction.on_commit(lambda: send_confirmation_email(event_id))

                # Deliberately trigger a rollback — the on_commit hook must NOT run
                raise Exception("Simulating an error!")

            else:
                return JsonResponse(
                    {'status': 'error', 'message': 'No seats available'},
                    status=400
                )
    except Event.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Event not found'},
            status=404
        )
    except Exception:
        # Transaction is rolled back; on_commit hooks are discarded
        return JsonResponse(
            {'status': 'error', 'message': 'Internal server error'},
            status=500
        )


@csrf_exempt
@require_POST
def book_optimistic(request, event_id):
    """
    SAFE endpoint using Optimistic Locking.

    Instead of holding a database lock, reads the current version of the event,
    then performs a conditional UPDATE that only succeeds if the version has not
    changed since the read. If another request modified the row first (version
    mismatch), the update affects 0 rows and a 409 Conflict is returned.

    This avoids lock contention and performs better under low-contention
    workloads, but requires the caller to handle 409 responses (e.g., retry).
    """
    try:
        with transaction.atomic():
            event = Event.objects.get(id=event_id)

            if event.booked_seats >= event.total_seats:
                return JsonResponse(
                    {'status': 'error', 'message': 'No seats available'},
                    status=400
                )

            # Conditional update: only succeeds if version matches what we read.
            # Uses atomic F() expressions so the DB does the increment safely.
            updated_rows = Event.objects.filter(
                id=event_id,
                version=event.version
            ).update(
                booked_seats=models.F('booked_seats') + 1,
                version=models.F('version') + 1
            )

            if updated_rows == 0:
                # Another transaction modified this row first — conflict detected
                return JsonResponse(
                    {'status': 'error', 'message': 'Conflict, please retry'},
                    status=409
                )

            Booking.objects.create(event_id=event_id, user_name='Test User')
            return JsonResponse({'status': 'success'}, status=201)

    except Event.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Event not found'},
            status=404
        )
    except Exception as e:
        logger.error(f"Unexpected error in book_optimistic: {e}")
        return JsonResponse(
            {'status': 'error', 'message': 'Internal server error'},
            status=500
        )


@require_http_methods(["GET"])
def event_status(request, event_id):
    """Returns current booking state of an event. Used by test script."""
    try:
        event = Event.objects.get(id=event_id)
        return JsonResponse({
            'id': event.id,
            'name': event.name,
            'total_seats': event.total_seats,
            'booked_seats': event.booked_seats,
            'version': event.version,
        })
    except Event.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Event not found'}, status=404)


@csrf_exempt
@require_POST
def event_reset(request, event_id):
    """
    Resets an event to its initial state (booked_seats=0, version=0)
    and deletes all associated bookings. Used between test runs.
    """
    try:
        with transaction.atomic():
            event = Event.objects.select_for_update().get(id=event_id)
            deleted_count, _ = event.bookings.all().delete()
            event.booked_seats = 0
            event.version = 0
            event.save()
        return JsonResponse({
            'status': 'reset',
            'booked_seats': 0,
            'bookings_deleted': deleted_count,
        })
    except Event.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Event not found'}, status=404)
