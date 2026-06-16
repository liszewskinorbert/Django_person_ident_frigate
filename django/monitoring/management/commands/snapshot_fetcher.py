"""
Demon nasłuchujący nowych zdarzeń bez snapshotu i pobierający je z Frigate API.
Sprawdza co POLL_INTERVAL sekund zdarzenia z has_snapshot=True i pustym thumbnail_url.
Uwzględnia tylko zdarzenia z ostatnich MAX_AGE_MINUTES minut (świeże).

Uruchomienie:
    python manage.py snapshot_fetcher
"""

import time
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from monitoring.models import CameraEvent
from monitoring import opencv_utils

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5       # sekund między sprawdzeniami
MAX_AGE_MINUTES = 60    # pobieraj snapshoty tylko dla zdarzeń młodszych niż X minut


class Command(BaseCommand):
    help = "Demon pobierający snapshoty z Frigate dla nowych zdarzeń (co kilka sekund)."

    def handle(self, *args, **options):
        self.stdout.write("Snapshot fetcher uruchomiony. Sprawdzam co %ds..." % POLL_INTERVAL)

        while True:
            try:
                self._fetch_pending()
            except Exception as exc:
                self.stderr.write(f"Błąd pętli snapshot_fetcher: {exc}")

            time.sleep(POLL_INTERVAL)

    def _fetch_pending(self):
        cutoff = timezone.now() - timedelta(minutes=MAX_AGE_MINUTES)

        pending = CameraEvent.objects.filter(
            has_snapshot=True,
            thumbnail_url="",
            started_at__gte=cutoff,
        ).order_by("started_at")

        for event in pending:
            try:
                result = opencv_utils.process_event_snapshot(event)
                event.snapshot_url = result["snapshot_url"]
                event.thumbnail_url = result["thumbnail_url"]
                event.save(update_fields=["snapshot_url", "thumbnail_url"])
                self.stdout.write(self.style.SUCCESS(
                    f"Snapshot OK: {event.camera_name} / {event.label} / {event.started_at:%H:%M:%S}"
                ))
            except Exception as exc:
                self.stderr.write(f"Błąd snapshotu {event.frigate_event_id}: {exc}")
