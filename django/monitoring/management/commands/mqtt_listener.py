"""
Komenda zarządzania Django: nasłuchuje zdarzeń MQTT publikowanych przez
Frigate na temacie `frigate/events` i zapisuje je jako rekordy CameraEvent.

Uruchomienie (np. jako usługa systemd):

    python manage.py mqtt_listener

Wymagane ustawienia w settings.py (z domyślnymi wartościami):

    MQTT_HOST = "localhost"
    MQTT_PORT = 1883
    MQTT_FRIGATE_TOPIC = "frigate/events"
    FRIGATE_BASE_URL = "http://localhost:5000"
    MEDIA_ROOT = BASE_DIR / "media"
"""

import json
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand

from monitoring import opencv_utils
from monitoring.models import CameraEvent, describe_label


MQTT_HOST = getattr(settings, "MQTT_HOST", "localhost")
MQTT_PORT = getattr(settings, "MQTT_PORT", 1883)
MQTT_TOPIC = getattr(settings, "MQTT_FRIGATE_TOPIC", "frigate/events")
FRIGATE_BASE_URL = getattr(settings, "FRIGATE_BASE_URL", "http://localhost:5000")


class Command(BaseCommand):
    help = "Nasłuchuje zdarzeń MQTT z Frigate i zapisuje je w bazie danych Django."

    def handle(self, *args, **options):
        client = mqtt.Client(client_id="django-monitoring")
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_disconnect = self.on_disconnect

        self.stdout.write(f"Łączenie z MQTT {MQTT_HOST}:{MQTT_PORT} ...")
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

        # loop_forever automatycznie próbuje ponownie połączyć się przy zerwaniu
        client.loop_forever()

    # ------------------------------------------------------------------
    # Callbacki MQTT
    # ------------------------------------------------------------------

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.stdout.write(self.style.SUCCESS(f"Połączono z MQTT. Subskrypcja: {MQTT_TOPIC}"))
            client.subscribe(MQTT_TOPIC)
        else:
            self.stderr.write(f"Błąd połączenia z MQTT, kod: {rc}")

    def on_disconnect(self, client, userdata, rc):
        self.stdout.write(self.style.WARNING(f"Rozłączono z MQTT (rc={rc}), ponawiam próbę..."))

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.stderr.write(f"Nieprawidłowy payload MQTT na {msg.topic}: {exc}")
            return

        event_type = payload.get("type")
        data = payload.get("after") or payload.get("before")
        if not data:
            return

        try:
            self.handle_event(event_type, data)
        except Exception as exc:  # noqa: BLE001 - log i kontynuuj nasłuchiwanie
            self.stderr.write(f"Błąd przetwarzania zdarzenia {data.get('id')}: {exc}")

    # ------------------------------------------------------------------
    # Logika zapisu zdarzenia
    # ------------------------------------------------------------------

    def handle_event(self, event_type, data):
        event_id = data["id"]
        started_at = datetime.fromtimestamp(data["start_time"], tz=timezone.utc)
        ended_at = (
            datetime.fromtimestamp(data["end_time"], tz=timezone.utc)
            if data.get("end_time")
            else None
        )

        event, created = CameraEvent.objects.update_or_create(
            frigate_event_id=event_id,
            defaults={
                "camera_name": data.get("camera", ""),
                "label": data.get("label", ""),
                "started_at": started_at,
                "ended_at": ended_at,
                "top_score": data.get("top_score"),
                "has_snapshot": bool(data.get("has_snapshot")),
                "has_clip": bool(data.get("has_clip")),
                "simple_description": describe_label(data.get("label", "")),
                "clip_url": f"{FRIGATE_BASE_URL}/api/events/{event_id}/clip.mp4" if data.get("has_clip") else "",
            },
        )

        action = "Nowe zdarzenie" if created else "Aktualizacja zdarzenia"
        self.stdout.write(f"{action}: {event}")

        # Snapshot przetwarzamy dopiero przy zakończeniu zdarzenia ("end"),
        # gdy Frigate ma już finalny kadr z najwyższą pewnością detekcji.
        if event_type == "end" and event.has_snapshot and not event.thumbnail_url:
            self.process_snapshot(event)

    def process_snapshot(self, event: CameraEvent) -> None:
        try:
            result = opencv_utils.process_event_snapshot(event)
        except Exception as exc:
            self.stderr.write(f"  -> błąd przetwarzania snapshotu (OpenCV): {exc}")
            return

        event.snapshot_url = result["snapshot_url"]
        event.thumbnail_url = result["thumbnail_url"]
        event.save(update_fields=["snapshot_url", "thumbnail_url"])
        self.stdout.write(self.style.SUCCESS("  -> snapshot przetworzony (OpenCV): pasek info + miniatura"))
