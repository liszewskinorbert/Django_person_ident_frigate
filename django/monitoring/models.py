from django.db import models


LABEL_DESCRIPTIONS = {
    "person": "Wykryto osobę.",
    "car": "Wykryto pojazd.",
    "dog": "Wykryto psa.",
    "cat": "Wykryto kota.",
}


def describe_label(label: str) -> str:
    """Zwraca prosty, regułowy opis zdarzenia na podstawie etykiety Frigate."""
    return LABEL_DESCRIPTIONS.get(label, f"Wykryto obiekt: {label}.")


class CameraEvent(models.Model):
    """
    Zdarzenie detekcji obiektu zarejestrowane przez Frigate dla jednej kamery.

    Rekord jest tworzony/aktualizowany przez komendę `mqtt_listener`, która
    nasłuchuje na temacie MQTT `frigate/events`.
    """

    frigate_event_id = models.CharField(max_length=100, unique=True)
    camera_name = models.CharField(max_length=100)
    label = models.CharField(max_length=50)

    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    top_score = models.FloatField(null=True, blank=True)
    has_snapshot = models.BooleanField(default=False)
    has_clip = models.BooleanField(default=False)

    snapshot_url = models.CharField(max_length=500, blank=True)
    thumbnail_url = models.CharField(max_length=500, blank=True)
    clip_url = models.CharField(max_length=500, blank=True)

    simple_description = models.TextField(blank=True)
    ai_description = models.TextField(blank=True)

    reviewed = models.BooleanField(default=False)
    false_alarm = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["camera_name"]),
            models.Index(fields=["label"]),
            models.Index(fields=["started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.camera_name} / {self.label} / {self.started_at:%Y-%m-%d %H:%M:%S}"
