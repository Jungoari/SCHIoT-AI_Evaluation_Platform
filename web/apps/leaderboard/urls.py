from django.urls import path

from . import views

app_name = "leaderboard"

urlpatterns = [
    path("p/<int:pk>/leaderboard/", views.leaderboard, name="page"),
    path("p/<int:pk>/leaderboard/table/", views.leaderboard_table, name="table"),
]
