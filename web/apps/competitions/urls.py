from django.urls import path

from . import views

app_name = "competitions"

urlpatterns = [
    path("c/new/", views.competition_create, name="create"),
    path("c/<int:pk>/", views.competition_detail, name="detail"),
    path("c/<int:pk>/codes/reissue/", views.code_reissue, name="code_reissue"),
    path("c/<int:pk>/members/", views.members, name="members"),
    path("c/<int:pk>/members/<int:mid>/", views.member_action, name="member_action"),
    path("c/<int:pk>/audit/", views.audit_log, name="audit"),
    path("c/<int:pk>/projects/new/", views.project_create, name="project_create"),
    path("p/<int:pk>/", views.project_detail, name="project_detail"),
    path("p/<int:pk>/settings/", views.project_settings, name="project_settings"),
    path("p/<int:pk>/files/<int:fid>/", views.project_file_download, name="project_file"),
    path("p/<int:pk>/results.csv", views.results_export, name="results_export"),
]
