"""
DIAMOR — intake HTTP layer (thin).

A single endpoint, POST /intake/candidates, that wraps the governed
intake.service.ingest_candidate operation. No business logic lives here:
the view does authentication, envelope-shape validation, and response mapping.

INTERNAL-ONLY (this step): access is gated by a shared-secret header
(X-Intake-Token vs the INTAKE_INTERNAL_TOKEN env var), failing closed if unset.
This is an interim guard to be REPLACED by server-verified Telegram identity /
operator authentication in a later step. actor_type/actor_id are taken from the
request body as a temporary placeholder for the same reason.
"""
import os
import secrets

from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from intake.serializers import IntakeRequestSerializer
from intake.service import ingest_candidate
from intake.validators import IntakeValidationError


class InternalTokenPermission(BasePermission):
    message = "Missing or invalid internal token."

    def has_permission(self, request, view):
        expected = os.environ.get("INTAKE_INTERNAL_TOKEN")
        if not expected:
            return False  # fail closed if not configured
        provided = request.headers.get("X-Intake-Token", "")
        return bool(provided) and secrets.compare_digest(provided, expected)


class IntakeCandidateView(APIView):
    # Explicit per-view config so global DRF defaults and diamor_runtime's
    # session/CSRF endpoints are unaffected. No SessionAuthentication => DRF does
    # not enforce CSRF on this token-authenticated, server-to-server endpoint.
    authentication_classes = []
    permission_classes = [InternalTokenPermission]

    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"error": "missing_idempotency_key",
                 "message": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        envelope = IntakeRequestSerializer(data=request.data)
        if not envelope.is_valid():
            return Response(
                {"error": "invalid_request", "details": envelope.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = envelope.validated_data

        try:
            result = ingest_candidate(
                payload=data["candidate"],
                idempotency_key=idempotency_key,
                channel=data["channel"],
                actor_type=data["actor"]["type"],
                actor_id=data["actor"]["id"],
            )
        except IntakeValidationError as exc:
            return Response(
                {"error": "validation_error", "field": exc.field, "message": exc.message},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ValueError as exc:
            return Response(
                {"error": "bad_request", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        body = {
            "outcome": result.outcome,
            "candidate_id": result.candidate_id,
            "submission_id": result.submission_id,
            "created": result.created,
            "consent_id": result.consent_id,
            "review_id": result.review_id,
        }
        http_status = (
            status.HTTP_201_CREATED if result.outcome == "created" else status.HTTP_200_OK
        )
        return Response(body, status=http_status)
