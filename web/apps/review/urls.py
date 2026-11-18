from django.urls import path

from . import views

app_name = "review"

urlpatterns = [
    path("p/<int:pk>/review/", views.review_queue, name="queue"),
    path("p/<int:pk>/review/bulk-approve/", views.bulk_approve, name="bulk_approve"),
    path("p/<int:pk>/results/", views.results, name="results"),
    path("review/<int:pk>/", views.review_detail, name="detail"),
    path("review/<int:pk>/propose/", views.review_propose, name="propose"),
    path("review/<int:pk>/decide/", views.review_decide, name="decide"),
    path("review/<int:pk>/notebook/", views.notebook_view, name="notebook"),
    path("review/<int:pk>/rerun/", views.rerun, name="rerun"),
]
