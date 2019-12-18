from __future__ import absolute_import

from django.conf.urls import url
from django.conf import settings

from .views import EolCompletionFragmentView


urlpatterns = (
    url(
        r'courses2/{}/student_completion/$'.format(
            settings.COURSE_ID_PATTERN,
        ),
        EolCompletionFragmentView.as_view(),
        name='completion_view',
    ),
)
