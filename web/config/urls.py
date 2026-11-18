from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
]

# Django 기본 관리 화면은 개발 중에만 노출 (운영에서는 관리 인터페이스 공격 면을 줄인다)
if settings.DEBUG:
    urlpatterns += [path("django-admin/", admin.site.urls)]

handler404 = "apps.core.views.error_404"
handler403 = "apps.core.views.error_403"
handler500 = "apps.core.views.error_500"
