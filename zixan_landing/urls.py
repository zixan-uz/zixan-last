from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('diamor/', include('diamor_runtime.urls')),
    path('', include('main.urls')),
]
