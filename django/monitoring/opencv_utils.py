import os
import datetime as dt
from zoneinfo import ZoneInfo

import cv2
import requests
from django.conf import settings
from django.utils import timezone

FRIGATE_BASE_URL = getattr(settings, "FRIGATE_BASE_URL", "http://localhost:5000")
SNAPSHOT_DIR = os.path.join(settings.MEDIA_ROOT, "snapshots")
THUMBNAIL_DIR = os.path.join(settings.MEDIA_ROOT, "thumbnails")
THUMBNAIL_WIDTH = 320
WARSAW_TZ = ZoneInfo("Europe/Warsaw")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)


def fetch_snapshot(event_id: str) -> str:
    url = f"{FRIGATE_BASE_URL}/api/events/{event_id}/snapshot.jpg"
    params = {"bbox": "1", "timestamp": "0", "h": "500", "best": "true"}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    snapshot_path = os.path.join(SNAPSHOT_DIR, f"{event_id}.jpg")
    with open(snapshot_path, "wb") as f:
        f.write(response.content)
    return snapshot_path


def annotate_snapshot(snapshot_path: str, label: str, score, started_at: dt.datetime) -> None:
    image = cv2.imread(snapshot_path)
    if image is None:
        raise ValueError(f"Nie udało się wczytać obrazu: {snapshot_path}")

    height, width = image.shape[:2]
    bar_height = 36

    canvas = cv2.copyMakeBorder(
        image, 0, bar_height, 0, 0,
        cv2.BORDER_CONSTANT, value=(20, 20, 20),
    )

    score_text = f"{score * 100:.0f}%" if score is not None else "n/a"

    if timezone.is_naive(started_at):
        started_at = timezone.make_aware(started_at, dt.timezone.utc)

    started_at_local = timezone.localtime(started_at, WARSAW_TZ)
    timestamp_text = started_at_local.strftime("%Y-%m-%d %H:%M:%S")
    text = f"{label.upper()}  |  pewnosc: {score_text}  |  {timestamp_text}"

    cv2.putText(
        canvas, text, (10, height + 24),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA,
    )
    cv2.imwrite(snapshot_path, canvas)


def generate_thumbnail(snapshot_path: str, event_id: str) -> str:
    image = cv2.imread(snapshot_path)
    if image is None:
        raise ValueError(f"Nie udało się wczytać obrazu: {snapshot_path}")

    height, width = image.shape[:2]
    scale = THUMBNAIL_WIDTH / width
    new_size = (THUMBNAIL_WIDTH, int(height * scale))
    thumbnail = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
    thumbnail_path = os.path.join(THUMBNAIL_DIR, f"{event_id}.jpg")
    cv2.imwrite(thumbnail_path, thumbnail)
    return thumbnail_path


def process_event_snapshot(event) -> dict:
    snapshot_path = fetch_snapshot(event.frigate_event_id)
    annotate_snapshot(snapshot_path, event.label, event.top_score, event.started_at)
    thumbnail_path = generate_thumbnail(snapshot_path, event.frigate_event_id)
    return {
        "snapshot_url": os.path.relpath(snapshot_path, settings.MEDIA_ROOT),
        "thumbnail_url": os.path.relpath(thumbnail_path, settings.MEDIA_ROOT),
    }
