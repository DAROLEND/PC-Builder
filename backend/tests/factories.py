import factory
from django.contrib.auth import get_user_model

from apps.builds.models import Build, BuildComponent


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.django.Password("S3cure-pass!")


class BuildFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Build

    owner = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Build {n}")
    is_public = True


def make_build(owner, components, *, name=None, is_public=True, quantities=None):
    build = BuildFactory(owner=owner, is_public=is_public, **({"name": name} if name else {}))
    quantities = quantities or {}
    BuildComponent.objects.bulk_create(
        BuildComponent(build=build, component=c, quantity=quantities.get(c.id, 1))
        for c in components
    )
    return build
