import os
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Avg
from django.db.models.functions import TruncDate, TruncHour
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import CameraEvent

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


def _find_recordings_for_event(event):
    """Zwraca URL jednego pliku wideo pasującego do daty/godziny/kamery zdarzenia.

    Frigate zapisuje klipy jako MM.SS-DURATION.mp4 w katalogu
    YYYY-MM-DD/HH/camera_name/. Szukamy pliku, którego minuta (MM) pokrywa
    się z minutą startu zdarzenia. Zwracamy listę z co najwyżej jednym elementem
    (dla zgodności z istniejącymi szablonami).
    """
    recordings_root = getattr(settings, "FRIGATE_RECORDINGS_PATH", "/media/frigate/recordings")
    if not os.path.isdir(recordings_root):
        return []

    local_dt = event.started_at.astimezone(LOCAL_TZ)
    date_str = local_dt.strftime("%Y-%m-%d")
    hour_str = local_dt.strftime("%H")
    camera_dir = os.path.join(recordings_root, date_str, hour_str, event.camera_name)

    if not os.path.isdir(camera_dir):
        # Fallback: szukaj w katalogu godziny bez podkatalogu kamery
        camera_dir = os.path.join(recordings_root, date_str, hour_str)
        if not os.path.isdir(camera_dir):
            return []

    event_minute = local_dt.strftime("%M")
    best = None

    for fname in sorted(os.listdir(camera_dir)):
        if not fname.lower().endswith((".mp4", ".mkv", ".avi")):
            continue
        # Frigate: MM.SS-DURATION.mp4 lub MM.SS.mp4
        file_minute = fname[:2]
        if file_minute == event_minute:
            best = fname
            break

    if best is None:
        return []

    rel = os.path.relpath(os.path.join(camera_dir, best), recordings_root)
    rel = rel.replace("\\", "/")
    return [f"/frigate-recordings/{rel}"]


@login_required
def event_list(request):
    events = CameraEvent.objects.all()

    camera = request.GET.get("camera")
    label = request.GET.get("label")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    status = request.GET.get("status")
    has_snapshot = request.GET.get("has_snapshot")
    has_clip = request.GET.get("has_clip")

    if camera:
        events = events.filter(camera_name=camera)
    if label:
        events = events.filter(label=label)
    if date_from:
        events = events.filter(started_at__date__gte=date_from)
    if date_to:
        events = events.filter(started_at__date__lte=date_to)
    if has_snapshot == "1":
        events = events.filter(has_snapshot=True)
    if has_clip == "1":
        events = events.filter(has_clip=True)
    if status == "reviewed":
        events = events.filter(reviewed=True)
    elif status == "unreviewed":
        events = events.filter(reviewed=False)
    elif status == "false_alarm":
        events = events.filter(false_alarm=True)

    paginator = Paginator(events, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "cameras": CameraEvent.objects.order_by().values_list("camera_name", flat=True).distinct(),
        "labels": CameraEvent.objects.order_by().values_list("label", flat=True).distinct(),
        "filters": request.GET,
        "total_count": events.count(),
    }
    return render(request, "monitoring/event_list.html", context)


@login_required
def event_detail(request, pk):
    event = get_object_or_404(CameraEvent, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_reviewed":
            event.reviewed = True
            event.false_alarm = False
            event.save(update_fields=["reviewed", "false_alarm"])
        elif action == "mark_false_alarm":
            event.false_alarm = True
            event.reviewed = True
            event.save(update_fields=["reviewed", "false_alarm"])
        elif action == "mark_unreviewed":
            event.reviewed = False
            event.false_alarm = False
            event.save(update_fields=["reviewed", "false_alarm"])
        return redirect("monitoring:event_detail", pk=pk)

    # Szukaj klipów na dysku
    disk_clips = _find_recordings_for_event(event)

    # Klip z Frigate API (jeśli istnieje)
    frigate_clip = event.clip_url if event.has_clip and event.clip_url else None

    context = {
        "event": event,
        "disk_clips": disk_clips,
        "frigate_clip": frigate_clip,
    }
    return render(request, "monitoring/event_detail.html", context)


@login_required
def mark_event(request, pk):
    """Szybka zmiana statusu zdarzenia z listy (POST AJAX lub zwykły form)."""
    if request.method != "POST":
        return redirect("monitoring:event_list")
    event = get_object_or_404(CameraEvent, pk=pk)
    action = request.POST.get("action")
    if action == "mark_reviewed":
        event.reviewed = True
        event.false_alarm = False
    elif action == "mark_false_alarm":
        event.false_alarm = True
        event.reviewed = True
    elif action == "mark_unreviewed":
        event.reviewed = False
        event.false_alarm = False
    event.save(update_fields=["reviewed", "false_alarm"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        if event.false_alarm:
            status = "false_alarm"
        elif event.reviewed:
            status = "reviewed"
        else:
            status = "new"
        return JsonResponse({"status": status})
    return redirect(request.POST.get("next", "monitoring:event_list"))


@login_required
def find_clip(request, pk):
    """JSON endpoint — zwraca listę znalezionych klipów dla zdarzenia."""
    event = get_object_or_404(CameraEvent, pk=pk)
    clips = _find_recordings_for_event(event)
    frigate_clip = event.clip_url if event.has_clip and event.clip_url else None
    return JsonResponse({"disk_clips": clips, "frigate_clip": frigate_clip})


@login_required
def statistics(request):
    total = CameraEvent.objects.count()
    reviewed = CameraEvent.objects.filter(reviewed=True).count()
    false_alarms = CameraEvent.objects.filter(false_alarm=True).count()
    unreviewed = CameraEvent.objects.filter(reviewed=False).count()

    by_label = (
        CameraEvent.objects.values("label")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    by_camera = (
        CameraEvent.objects.values("camera_name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    by_date = (
        CameraEvent.objects.annotate(date=TruncDate("started_at"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("-date")[:30]
    )

    by_hour = (
        CameraEvent.objects.annotate(hour=TruncHour("started_at"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )

    hour_buckets = [0] * 24
    for row in by_hour:
        h = row["hour"].astimezone(LOCAL_TZ).hour
        hour_buckets[h] += row["count"]

    avg_score = CameraEvent.objects.aggregate(avg=Avg("top_score"))["avg"]

    context = {
        "total": total,
        "reviewed": reviewed,
        "false_alarms": false_alarms,
        "unreviewed": unreviewed,
        "by_label": list(by_label),
        "by_camera": list(by_camera),
        "by_date": list(by_date),
        "hour_buckets": hour_buckets,
        "avg_score": avg_score,
    }
    return render(request, "monitoring/statistics.html", context)


@login_required
def camera_preview(request):
    cameras = list(
        CameraEvent.objects.order_by()
        .values_list("camera_name", flat=True)
        .distinct()
    )
    frigate_url = getattr(settings, "FRIGATE_BASE_URL", "http://localhost:5000")

    # Ostatnie zdarzenie dla każdej kamery
    latest = {}
    for cam in cameras:
        ev = CameraEvent.objects.filter(camera_name=cam).order_by("-started_at").first()
        latest[cam] = ev

    context = {
        "cameras": cameras,
        "latest": latest,
        "frigate_url": frigate_url,
    }
    return render(request, "monitoring/camera_preview.html", context)
