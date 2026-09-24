from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Component

from . import compatibility

LINE_TOTAL = ExpressionWrapper(
    F("build_components__component__price") * F("build_components__quantity"),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)


class BuildQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Public builds plus the user's own private ones."""
        if user.is_authenticated:
            return self.filter(Q(is_public=True) | Q(owner=user))
        return self.filter(is_public=True)

    def with_total_price(self):
        # Coalesce so an empty build reports 0.00 instead of NULL.
        return self.annotate(
            total_price=Coalesce(
                Sum(LINE_TOTAL),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )

    def with_parts(self):
        """Everything the detail serializer and the compatibility check need.

        Without this, serializing N builds costs 1 + N (lines) + N*M (components)
        + N*M (categories) queries. With it the count is constant.
        """
        return self.select_related("owner").prefetch_related(
            models.Prefetch(
                "build_components",
                queryset=BuildComponent.objects.select_related(
                    "component__category", "component__manufacturer"
                )
                .prefetch_related("component__listings", "component__photos")
                .order_by("component__category__position", "id"),
            )
        )


class Build(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="builds"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=False)
    components = models.ManyToManyField(Component, through="BuildComponent", related_name="builds")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BuildQuerySet.as_manager()

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="build_unique_name_per_owner"),
        ]

    def __str__(self) -> str:
        return self.name

    def parts(self) -> list[compatibility.Part]:
        """Adapt ORM rows to engine parts. Uses the prefetch cache when present."""
        return [
            compatibility.Part(
                id=line.component.id,
                kind=line.component.category.kind,
                name=str(line.component),
                specs=line.component.specs,
                quantity=line.quantity,
            )
            for line in self.build_components.all()
        ]

    def compatibility_report(self) -> compatibility.Report:
        return compatibility.check(self.parts())

    def compute_total(self) -> Decimal:
        return sum(
            (line.component.price * line.quantity for line in self.build_components.all()),
            Decimal("0.00"),
        )


class BuildComponent(models.Model):
    """Through model: which component is in which build and how many of it."""

    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="build_components")
    component = models.ForeignKey(
        Component, on_delete=models.PROTECT, related_name="build_components"
    )
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["build", "component"], name="build_component_unique"),
            # Hard ceiling in the database; the per-kind limits (1 CPU, 2 GPUs...)
            # live in the compatibility engine because they depend on the category.
            models.CheckConstraint(
                condition=Q(quantity__gte=1) & Q(quantity__lte=8),
                name="build_component_quantity_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.component}"

    @property
    def line_total(self) -> Decimal:
        return self.component.price * self.quantity


class Comment(models.Model):
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    text = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.author} on {self.build}"
