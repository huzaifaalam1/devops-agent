from django.http import HttpResponse
from django.urls import path


def ready(request):
    return HttpResponse('django-step5-ready')


urlpatterns = [path('', ready)]
