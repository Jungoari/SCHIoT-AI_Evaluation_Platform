from django.conf import settings


def site(request):
    """모든 템플릿에서 쓰는 공통 값"""
    return {
        "DEMO_MODE": settings.DEMO_MODE,
        "SITE_NAME": "AI모델 성능평가",
    }
