"""
DIAMOR — intake HTTP request serializers.

These validate the HTTP ENVELOPE shape only (channel, actor, candidate present
and well-typed). Deep candidate validation and normalization is performed by
intake.service / intake.validators, which remain the single source of truth.
"""
from rest_framework import serializers


class ActorSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class IntakeRequestSerializer(serializers.Serializer):
    channel = serializers.CharField()
    actor = ActorSerializer()
    candidate = serializers.DictField()
