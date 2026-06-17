from django.shortcuts import render

def home(request):
    return render(request, 'base.html')

def left_sidebar(request):
    return render(request, 'left_sidebar.html')

def right_sidebar(request):
    return render(request, 'right_sidebar.html')

def no_sidebar(request):
    return render(request, 'no_sidebar.html')
