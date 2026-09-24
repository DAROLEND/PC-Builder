from django.urls import path

from . import views

urlpatterns = [
    path("categories/", views.CategoryStatsView.as_view(), name="stats-categories"),
    path("popular-components/", views.PopularComponentsView.as_view(), name="stats-popular"),
    path("top-per-category/", views.TopPerCategoryView.as_view(), name="stats-top-per-category"),
    path("price-position/", views.PricePositionView.as_view(), name="stats-price-position"),
    path("cheapest-build/", views.CheapestBuildWithGpuView.as_view(), name="stats-cheapest-build"),
]
