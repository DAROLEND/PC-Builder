from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Read access follows queryset visibility; writes are owner-only.

    Visibility (public builds + your own private ones) is enforced by
    ``Build.objects.visible_to()`` in ``get_queryset``, so another user's
    private build is a 404, not a 403 — we don't reveal that it exists.
    This class only decides who may *modify* an object they can already see.
    """

    message = "Only the owner of this build can modify it."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.owner_id == request.user.id


class IsCommentAuthorOrBuildOwner(permissions.BasePermission):
    """Authors can edit and delete their comments; build owners can moderate
    (delete, but not rewrite) comments left on their builds."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if obj.author_id == request.user.id:
            return True
        return request.method == "DELETE" and obj.build.owner_id == request.user.id
