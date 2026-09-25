"""Django storage backend that keeps files in PostgreSQL (``StoredFile``).

Enabled with ``MEDIA_STORAGE=db``. The API serves the files itself (see
``serve_stored_file``) with long cache headers, since mirrored photos never
change: a new photo gets a new name.
"""

from __future__ import annotations

import mimetypes

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.http import Http404, HttpResponse
from django.utils.deconstruct import deconstructible
from django.utils.encoding import filepath_to_uri
from django.views.decorators.http import require_safe

CACHE_SECONDS = 30 * 24 * 60 * 60


@deconstructible
class DatabaseStorage(Storage):
    def _open(self, name: str, mode: str = "rb") -> ContentFile:
        from .models import StoredFile

        content = StoredFile.objects.filter(name=name).values_list("content", flat=True).first()
        if content is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(content), name=name)

    def _save(self, name: str, content) -> str:
        from .models import StoredFile

        data = b"".join(content.chunks())
        StoredFile.objects.create(name=name, content=data, size=len(data))
        return name

    def get_available_name(self, name: str, max_length: int | None = None) -> str:
        # Storage builds candidates with os.path: keep the stored names POSIX on
        # Windows too, since they double as URL paths.
        return super().get_available_name(name, max_length).replace("\\", "/")

    def exists(self, name: str) -> bool:
        from .models import StoredFile

        return StoredFile.objects.filter(name=name).exists()

    def delete(self, name: str) -> None:
        from .models import StoredFile

        StoredFile.objects.filter(name=name).delete()

    def size(self, name: str) -> int:
        from .models import StoredFile

        size = StoredFile.objects.filter(name=name).values_list("size", flat=True).first()
        if size is None:
            raise FileNotFoundError(name)
        return size

    def url(self, name: str) -> str:
        return settings.MEDIA_URL + filepath_to_uri(name)


@require_safe
def serve_stored_file(request, path: str) -> HttpResponse:
    from .models import StoredFile

    content = StoredFile.objects.filter(name=path).values_list("content", flat=True).first()
    if content is None:
        raise Http404(path)
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    response = HttpResponse(bytes(content), content_type=content_type)
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}, immutable"
    return response
