from django.urls import path

from . import views

app_name = "submissions"

urlpatterns = [
    path("p/<int:pk>/submit/start/", views.submit_start, name="start"),
    path("s/<uuid:pk>/upload/", views.submit_upload, name="upload"),
    path("s/<uuid:pk>/status/", views.submission_status, name="status"),
    path("s/<uuid:pk>/", views.submission_detail, name="detail"),
    path("s/<uuid:pk>/download/<str:kind>/", views.submission_download, name="download"),
]
