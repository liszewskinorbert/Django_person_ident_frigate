from django.urls import path
from . import views

app_name = "monitoring"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("<int:pk>/", views.event_detail, name="event_detail"),
    path("statistics/", views.statistics, name="statistics"),
    path("camera/", views.camera_preview, name="camera_preview"),
    path("<int:pk>/clip/", views.find_clip, name="find_clip"),
    path("<int:pk>/mark/", views.mark_event, name="mark_event"),
]
