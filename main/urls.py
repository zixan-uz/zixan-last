from django.urls import path
from .views import home, left_sidebar, right_sidebar, no_sidebar

urlpatterns = [
    path('', home, name='home'),
    path('left-sidebar/', left_sidebar, name='left_sidebar'),
    path('right-sidebar/', right_sidebar, name='right_sidebar'),
    path('no-sidebar/', no_sidebar, name='no_sidebar'),
]
