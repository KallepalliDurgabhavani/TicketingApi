from django.db import models


class Event(models.Model):
    name = models.CharField(max_length=200)
    total_seats = models.PositiveIntegerField()
    booked_seats = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=0)  # For optimistic locking

    class Meta:
        app_label = 'tickets'

    def __str__(self):
        return f"{self.name} ({self.booked_seats}/{self.total_seats} seats booked)"


class Booking(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='bookings')
    user_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'tickets'

    def __str__(self):
        return f"Booking by {self.user_name} for {self.event.name}"
