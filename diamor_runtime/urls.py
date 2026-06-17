from django.urls import path

from . import views

app_name = "diamor_runtime"

urlpatterns = [
    path("phase1/whoami", views.whoami, name="whoami"),
    path("phase1/disclosure/decide", views.disclosure_decision, name="disclosure_decide"),
]
