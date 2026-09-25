import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import RequestFactory

from apps.catalog.db_storage import DatabaseStorage, serve_stored_file
from apps.catalog.models import ProductImage, StoredFile

pytestmark = pytest.mark.django_db

DB_STORAGES = {
    "default": {"BACKEND": "apps.catalog.db_storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def test_database_storage_roundtrip():
    storage = DatabaseStorage()
    name = storage.save("products/thumbs/cpu-0.webp", ContentFile(b"RIFFwebp"))
    assert name == "products/thumbs/cpu-0.webp"
    assert storage.exists(name)
    assert storage.size(name) == 8
    assert storage.url(name) == "/media/products/thumbs/cpu-0.webp"
    with storage.open(name) as f:
        assert f.read() == b"RIFFwebp"

    # Same name again: the storage picks a free one instead of overwriting.
    second = storage.save("products/thumbs/cpu-0.webp", ContentFile(b"other"))
    assert second != name and second.startswith("products/thumbs/cpu-0")

    storage.delete(name)
    assert not storage.exists(name)
    with pytest.raises(FileNotFoundError):
        storage.open(name)


def test_product_photos_go_to_the_database(settings, comp):
    settings.STORAGES = DB_STORAGES
    photo = ProductImage(component=comp("Ryzen 5 7600"), source_url="https://img.example/1.jpg")
    photo.thumb.save("r5-0.webp", ContentFile(b"thumb"), save=False)
    photo.large.save("r5-0.webp", ContentFile(b"large"), save=False)
    photo.save()

    assert isinstance(default_storage._wrapped, DatabaseStorage)
    assert StoredFile.objects.count() == 2
    assert photo.thumb.url == "/media/products/thumbs/r5-0.webp"


def test_serve_stored_file_with_cache_headers():
    StoredFile.objects.create(name="products/large/gpu-0.webp", content=b"RIFFgpu", size=7)
    request = RequestFactory().get("/media/products/large/gpu-0.webp")
    response = serve_stored_file(request, "products/large/gpu-0.webp")
    assert response.status_code == 200
    assert response.content == b"RIFFgpu"
    assert response["Content-Type"] == "image/webp"
    assert "immutable" in response["Cache-Control"]


def test_serve_stored_file_missing_is_404():
    from django.http import Http404

    with pytest.raises(Http404):
        serve_stored_file(RequestFactory().get("/media/nope.webp"), "nope.webp")
