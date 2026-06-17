from django.contrib import admin

from .models import CameraEvent


@admin.register(CameraEvent)
class CameraEventAdmin(admin.ModelAdmin):
    list_display = (
        "camera_name",
        "label",
        "started_at",
        "top_score",
        "has_snapshot",
        "has_clip",
        "reviewed",
        "false_alarm",
    )
    list_filter = ("camera_name", "label", "reviewed", "false_alarm", "has_snapshot", "has_clip")
    search_fields = ("frigate_event_id", "camera_name", "label")
    date_hierarchy = "started_at"
