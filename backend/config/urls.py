from csp.constants import UNSAFE_INLINE
from csp.decorators import csp_update
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

# Swagger UI loads its bundle from jsDelivr and has an inline <style>; widen the CSP
# for this one page only. The split view serves its init script as a same-origin file,
# so no inline script is needed.
SWAGGER_CDN = "https://cdn.jsdelivr.net"
docs_view = csp_update(
    {
        "script-src": [SWAGGER_CDN],
        "style-src": [SWAGGER_CDN, UNSAFE_INLINE],
        "img-src": [SWAGGER_CDN],
    }
)(SpectacularSwaggerSplitView.as_view(url_name="schema"))

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("config.api_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", docs_view, name="docs"),
]
