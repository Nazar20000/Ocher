from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Очередь к стиралкам"
admin.site.site_title = "Очередь"
admin.site.index_title = "Стиралки"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("laundry.urls")),
]
