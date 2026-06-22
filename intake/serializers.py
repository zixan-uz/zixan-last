"""
DIAMOR — intake HTTP request serializers.

Validates the HTTP ENVELOPE shape only (channel, actor, candidate, identifiers).
Deep candidate/identifier validation and normalization is performed by
intake.service / intake.validators, the single source of truth.
"""
from rest_framework import serializers


class ActorSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class IdentifierSerializer(serializers.Serializer):
    channel = serializers.CharField()
    identifier_type = serializers.CharField()
    identifier_value = serializers.CharField()
    source_attribution = serializers.DictField(required=False, default=dict)


class IntakeRequestSerializer(serializers.Serializer):
    channel = serializers.CharField()
    actor = ActorSerializer()
    candidate = serializers.DictField()
    identifiers = IdentifierSerializer(many=True)
