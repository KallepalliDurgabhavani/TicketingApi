from django.core.management.base import BaseCommand

from tickets.models import Event


class Command(BaseCommand):
    help = 'Seeds the database with the initial event required for testing'

    def handle(self, *args, **options):
        event, created = Event.objects.get_or_create(
            id=1,
            defaults={
                'name': 'Tech Conference 2024',
                'total_seats': 30,
                'booked_seats': 0,
                'version': 0,
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully created seed event: "{event.name}" '
                    f'with {event.total_seats} total seats (id={event.id})'
                )
            )
        else:
            # Reset the event for a clean test run
            event.booked_seats = 0
            event.version = 0
            event.save()
            # Remove existing bookings for a fresh start
            deleted_count, _ = event.bookings.all().delete()
            self.stdout.write(
                self.style.WARNING(
                    f'Event id=1 already exists. Reset booked_seats=0 and '
                    f'deleted {deleted_count} existing bookings.'
                )
            )
