from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("m/<int:number>/", views.machine_detail, name="machine"),
    path("m/<int:number>/join/", views.join, name="join"),
    path("queue/<int:entry_id>/complete/", views.complete, name="complete"),
    path("queue/<int:entry_id>/leave/", views.leave, name="leave"),
    path("profile/", views.profile, name="profile"),
    path("profile/telegram/disconnect/", views.telegram_disconnect, name="telegram_disconnect"),
    path("telegram/webhook/<str:secret>/", views.telegram_webhook, name="telegram_webhook"),
]
