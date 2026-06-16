"""
Jednorazowa komenda naprawiająca stare clip_url w bazie danych.
Stary format: {event_id}/clip
Nowy format:  http://localhost:5000/api/events/{event_id}/clip.mp4

Uruchomienie:
    python manage.py fix_clip_urls
"""

from django.core.management.base import BaseCommand
from django.conf import settings
from monitoring.models import CameraEvent

FRIGATE_BASE_URL = getattr(settings, "FRIGATE_BASE_URL", "http://localhost:5000")


class Command(BaseCommand):
    help = "Naprawia stare clip_url w bazie danych (jednorazowe uruchomienie)."

    def handle(self, *args, **options):
        fixed = 0
        for event in CameraEvent.objects.filter(has_clip=True).exclude(clip_url=""):
            url = event.clip_url
            # stary format: "{event_id}/clip" lub samo "{event_id}"
            if not url.startswith("http"):
                event_id = event.frigate_event_id
                event.clip_url = f"{FRIGATE_BASE_URL}/api/events/{event_id}/clip.mp4"
                event.save(update_fields=["clip_url"])
                fixed += 1
                self.stdout.write(f"Naprawiono: {event_id}")

        self.stdout.write(self.style.SUCCESS(f"\nGotowe: naprawiono {fixed} rekordów."))
