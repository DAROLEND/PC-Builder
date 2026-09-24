from decimal import Decimal

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from apps.builds.serializers import CompatibilityReportSerializer
from apps.catalog.models import ExchangeRate
from apps.catalog.serializers import ComponentBriefSerializer

from .planner import USE_CASES


# COMPONENT_SPLIT_REQUEST appends "Request" → the schema name becomes "AdvisorRequest".
@extend_schema_serializer(component_name="Advisor")
class AdvisorRequestSerializer(serializers.Serializer):
    MIN_USD, MAX_USD = Decimal(300), Decimal(20000)

    budget = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=1, help_text="Amount in `currency`."
    )
    currency = serializers.ChoiceField(
        choices=["USD", "UAH"],
        default="USD",
        help_text="UAH budgets are converted at the latest NBU rate; the catalog plans in USD.",
    )
    use_case = serializers.ChoiceField(choices=USE_CASES)
    preferences = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    language = serializers.ChoiceField(
        choices=["en", "uk"], default="en", help_text="Language of the summary and notes."
    )

    def validate(self, attrs):
        rate = None
        if attrs["currency"] == "UAH":
            rate = ExchangeRate.latest_uah_rate()
            if not rate:
                raise serializers.ValidationError(
                    {"currency": "No UAH exchange rate is loaded yet; enter the budget in USD."}
                )
            usd = (attrs["budget"] / rate).quantize(Decimal("0.01"))
        else:
            usd = attrs["budget"]
        if not self.MIN_USD <= usd <= self.MAX_USD:
            if rate:
                low, high = (round(self.MIN_USD * rate, -2), round(self.MAX_USD * rate, -2))
                message = f"The budget must be between {low:,.0f} and {high:,.0f} UAH."
            else:
                message = f"The budget must be between ${self.MIN_USD:,} and ${self.MAX_USD:,}."
            raise serializers.ValidationError({"budget": message})
        attrs["budget_usd"] = usd
        attrs["uah_rate"] = rate
        return attrs


class AdvisorResponseSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=["claude", "rule_based"])
    model = serializers.CharField(allow_blank=True)
    summary = serializers.CharField()
    notes = serializers.ListField(child=serializers.CharField())
    components = ComponentBriefSerializer(many=True)
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    budget = serializers.DecimalField(max_digits=8, decimal_places=2, help_text="USD")
    budget_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="The budget as entered, in `budget_currency`."
    )
    budget_currency = serializers.ChoiceField(choices=["USD", "UAH"])
    compatibility = CompatibilityReportSerializer()
