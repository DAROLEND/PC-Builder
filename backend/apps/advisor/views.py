from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import AdvisorRequestSerializer, AdvisorResponseSerializer
from .service import Money, advise


class AdvisorView(APIView):
    """Recommend a complete, compatible build for a budget and use case.

    Logged-in users only and rate limited: each call may cost LLM tokens.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "advisor"

    @extend_schema(request=AdvisorRequestSerializer, responses=AdvisorResponseSerializer)
    def post(self, request):
        serializer = AdvisorRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = advise(
            budget=data["budget_usd"],
            use_case=data["use_case"],
            preferences=data["preferences"],
            language=data["language"],
            display=Money(data["budget"], data["currency"], data["uah_rate"]),
        )
        return Response(AdvisorResponseSerializer(result).data)
