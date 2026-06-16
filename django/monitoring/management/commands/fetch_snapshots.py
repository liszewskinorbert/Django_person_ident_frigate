"""
Komenda do retroaktywnego pobierania snapshotów dla zdarzeń,
które mają has_snapshot=True ale nie mają jeszcze zapisanego thumbnail_url.

Uruchomienie:
    python manage.py fetch_snapshots
    python manage.py fetch_snapshots --limit 50
"""

from django.core.management.base import BaseCommand
from monitoring.models import CameraEvent
from monitoring import opencv_utils


class Command(BaseCommand):
    help = "Pobiera brakujące snapshoty z Frigate API dla istniejących zdarzeń."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maksymalna liczba zdarzeń do przetworzenia (0 = wszystkie).",
        )

    def handle(self, *args, **options):
        qs = CameraEvent.objects.filter(
            has_snapshot=True,
            thumbnail_url="",
        ).order_by("-started_at")

        limit = options["limit"]
        if limit:
            qs = qs[:limit]

        total = qs.count() if not limit else min(qs.count(), limit)
        self.stdout.write(f"Znaleziono {total} zdarzeń bez snapshotu.")

        ok = 0
        fail = 0
        for event in qs:
            try:
                result = opencv_utils.process_event_snapshot(event)
                event.snapshot_url = result["snapshot_url"]
                event.thumbnail_url = result["thumbnail_url"]
                event.save(update_fields=["snapshot_url", "thumbnail_url"])
                self.stdout.write(self.style.SUCCESS(f"  OK  {event}"))
                ok += 1
            except Exception as exc:
                self.stderr.write(f"  ERR {event}: {exc}")
                fail += 1

        self.stdout.write(f"\nGotowe: {ok} OK, {fail} błędów.")
