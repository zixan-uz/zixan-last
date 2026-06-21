from django.urls import path

from intake.views import IntakeCandidateView

app_name = "intake"

urlpatterns = [
    path("candidates", IntakeCandidateView.as_view(), name="candidates"),
]
