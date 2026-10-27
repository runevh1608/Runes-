from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("log-ind/", auth_views.LoginView.as_view(), name="login"),
    path("log-ud/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("", include("likvid.urls")),
]
