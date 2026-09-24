from rest_framework import serializers

from apps.builds.models import Build

from .models import TRANSITIONS, Order, OrderItem, OrderStatus


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "component", "component_name", "unit_price", "quantity", "line_total"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "build",
            "status",
            "total",
            "shipping_address",
            "payment_provider",
            "items",
            "allowed_transitions",
            "created_at",
            "updated_at",
            "paid_at",
        ]

    def get_allowed_transitions(self, obj: Order) -> list[str]:
        return sorted(TRANSITIONS[obj.status])


class OrderCreateSerializer(serializers.Serializer):
    build = serializers.PrimaryKeyRelatedField(queryset=Build.objects.all())
    shipping_address = serializers.CharField(max_length=500)

    def validate_build(self, build: Build) -> Build:
        user = self.context["request"].user
        # You can order your own builds and anyone's public builds.
        if not (build.is_public or build.owner_id == user.id):
            raise serializers.ValidationError("Build not found.")
        return build


class PaymentSessionSerializer(serializers.Serializer):
    provider = serializers.CharField()
    checkout_url = serializers.URLField(allow_null=True)
    confirmed = serializers.BooleanField()
    order = OrderSerializer()


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
