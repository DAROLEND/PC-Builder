from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from config.celery import enqueue_best_effort

from . import compatibility
from .filters import BuildFilter
from .models import Build, BuildComponent, Comment
from .permissions import IsCommentAuthorOrBuildOwner, IsOwnerOrReadOnly
from .serializers import (
    BuildDetailSerializer,
    BuildListSerializer,
    BuildWriteSerializer,
    CommentSerializer,
    CompatibilityCheckSerializer,
    CompatibilityReportSerializer,
    items_to_parts,
)
from .tasks import notify_build_owner_about_comment


def comments_count_subquery():
    # A Subquery instead of Count("comments"): two aggregates over two
    # different joins (components and comments) multiply each other's rows,
    # so Sum(price) would be inflated by the number of comments.
    return Coalesce(
        Subquery(
            Comment.objects.filter(build=OuterRef("pk"))
            .values("build")
            .annotate(n=Count("id"))
            .values("n"),
            output_field=IntegerField(),
        ),
        Value(0),
    )


@extend_schema_view(
    create=extend_schema(request=BuildWriteSerializer, responses=BuildDetailSerializer),
    update=extend_schema(request=BuildWriteSerializer, responses=BuildDetailSerializer),
    partial_update=extend_schema(request=BuildWriteSerializer, responses=BuildDetailSerializer),
)
class BuildViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    filterset_class = BuildFilter
    search_fields = ["name", "description"]
    ordering_fields = ["total_price", "updated_at", "created_at", "name"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        qs = Build.objects.visible_to(self.request.user).with_total_price()
        if self.action == "list":
            return qs.select_related("owner").annotate(
                parts_count=Coalesce(Sum("build_components__quantity"), Value(0)),
                comments_count=comments_count_subquery(),
            )
        return qs.with_parts()

    def get_serializer_class(self):
        if self.action == "list":
            return BuildListSerializer
        if self.action in {"create", "update", "partial_update"}:
            return BuildWriteSerializer
        if self.action == "comments":
            return CommentSerializer
        return BuildDetailSerializer

    @extend_schema(responses=CompatibilityReportSerializer)
    @action(detail=True, methods=["get"])
    def compatibility(self, request, pk=None):
        build = self.get_object()
        return Response(build.compatibility_report().as_dict())

    @extend_schema(request=None, responses={201: BuildDetailSerializer})
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def clone(self, request, pk=None):
        """Copy a visible build (e.g. someone's public build) into your own builds."""
        source = self.get_object()
        base = f"Copy of {source.name}"[:90]
        name, n = base, 2
        while Build.objects.filter(owner=request.user, name=name).exists():
            name, n = f"{base} ({n})", n + 1
        with transaction.atomic():
            clone = Build.objects.create(
                owner=request.user, name=name, description=source.description, is_public=False
            )
            BuildComponent.objects.bulk_create(
                BuildComponent(build=clone, component=line.component, quantity=line.quantity)
                for line in source.build_components.all()
            )
        fresh = Build.objects.with_parts().with_total_price().get(pk=clone.pk)
        return Response(BuildDetailSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        methods=["get"], responses=CommentSerializer(many=True), summary="List build comments"
    )
    @extend_schema(
        methods=["post"],
        request=CommentSerializer,
        responses={201: CommentSerializer},
        summary="Comment on a build",
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def comments(self, request, pk=None):
        build = self.get_object()
        if request.method == "GET":
            rows = build.comments.select_related("author")
            return Response(CommentSerializer(rows, many=True).data)

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(build=build, author=request.user)
        if build.owner_id != request.user.id:
            # on_commit: the worker must not pick up the task before the row exists.
            transaction.on_commit(
                lambda: enqueue_best_effort(notify_build_owner_about_comment, comment.id)
            )
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    def get_permissions(self):
        if self.action == "comments" and self.request.method == "POST":
            # Commenting does not require owning the build, only being logged in.
            return [permissions.IsAuthenticated()]
        return super().get_permissions()


class CommentViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsCommentAuthorOrBuildOwner]

    def get_queryset(self):
        visible = Build.objects.visible_to(self.request.user)
        return Comment.objects.filter(build__in=visible).select_related("author", "build")


class CompatibilityCheckView(APIView):
    """Check an unsaved set of components. Used by the configurator for live feedback."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(request=CompatibilityCheckSerializer, responses=CompatibilityReportSerializer)
    def post(self, request):
        serializer = CompatibilityCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = compatibility.check(items_to_parts(serializer.validated_data["items"]))
        return Response(report.as_dict())
