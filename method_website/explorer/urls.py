from django.urls import path
from . import views
from .comparison_job_views import comparison_job_status

urlpatterns = [
    path("", views.welcome_page, name="home"),
    path("explorer/welcome", views.welcome_page, name="welcome"),
    path("reproduction/", views.reproduction_page, name="reproduction"),
    path(
        "explorer/chelton/detection/",
        views.chelton_detection_page,
        name="chelton_detection",
    ),
    path(
        "explorer/chelton/tracking/",
        views.chelton_tracking_page,
        name="chelton_tracker",
    ),
    path(
        "methods/chelton/methodology/",
        views.chelton_methodology_page,
        name="chelton_methodology",
    ),
    path(
        "explorer/nencioli/detection/",
        views.nencioli_detection_page,
        name="nencioli_detection",
    ),
    path(
        "explorer/nencioli/tracking/",
        views.nencioli_tracking_page,
        name="nencioli_tracker",
    ),
    path(
        "methods/nencioli/methodology/",
        views.nencioli_methodology_page,
        name="nencioli_methodology",
    ),
    path("explorer/halo/tracking/", views.halo_tracking_page, name="halo_tracker"),
    path("explorer/halo/detection", views.halo_page, name="halo_detection"),
    path(
        "methods/halo/methodology/",
        views.halo_methodology_page,
        name="halo_methodology",
    ),
    path(
        "explorer/compare/jobs/<str:job_id>/status/",
        comparison_job_status,
        name="comparison_job_status",
    ),
    path("explorer/compare", views.comparison_page, name="comparison"),
    path(
        "methods/comparison/methodology/",
        views.comparison_methodology_page,
        name="comparison_methodology",
    ),
    path("explorer/available-dates/", views.available_dates, name="available_dates"),
]
