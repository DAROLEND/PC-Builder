from django.contrib import admin

from .models import Build, BuildComponent, Comment


class BuildComponentInline(admin.TabularInline):
    model = BuildComponent
    extra = 0
    autocomplete_fields = ["component"]


@admin.register(Build)
class BuildAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "is_public", "updated_at"]
    list_filter = ["is_public"]
    search_fields = ["name", "owner__username"]
    inlines = [BuildComponentInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["build", "author", "created_at"]
    search_fields = ["text"]
