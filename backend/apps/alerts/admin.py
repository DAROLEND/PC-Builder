from django.contrib import admin

from .models import TelegramLink, Watch


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ["user", "username", "linked", "enabled", "quiet_hours", "language", "linked_at"]
    list_filter = ["enabled", "language"]
    search_fields = ["user__username", "username"]
    readonly_fields = ["chat_id", "link_token", "token_created_at", "linked_at"]

    @admin.display(boolean=True)
    def linked(self, obj):
        return obj.linked


@admin.register(Watch)
class WatchAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "component",
        "build",
        "threshold_percent",
        "target_price",
        "baseline_price",
        "last_notified_at",
    ]
    list_select_related = ["user", "component__manufacturer", "build"]
    raw_id_fields = ["component", "build"]
