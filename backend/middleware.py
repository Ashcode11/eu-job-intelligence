"""Request-ID propagation, access logging and Prometheus HTTP metrics."""

import time
import uuid

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from common.logging import get_logger

log = get_logger("http")

HTTP_REQUESTS = Counter(
    "eujobs_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "eujobs_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

_QUIET_PATHS = {"/health/live", "/health/ready", "/metrics"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 64 else uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            # Use the route template (/jobs/{job_id}) so label cardinality stays bounded.
            route_label = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route_label, str(status_code)).inc()
            HTTP_LATENCY.labels(request.method, route_label).observe(elapsed)
            if request.url.path not in _QUIET_PATHS:
                log.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    route=route_label,
                    status=status_code,
                    duration_ms=round(elapsed * 1000, 1),
                )
        response.headers["X-Request-ID"] = request_id
        return response
