"""Bounded request IDs and JSON completion/error records without request bodies."""
import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi.responses import JSONResponse


logger = logging.getLogger("fleetsignal")


def install_error_handling(application):
    """Generate safe errors inside CORS so they retain allowed origin headers."""
    @application.middleware("http")
    async def safe_errors(request, call_next):
        try:
            return await call_next(request)
        except Exception:
            request_id = request.state.request_id
            logger.exception(json.dumps(dict(event="request_error", request_id=request_id,
                                             method=request.method,
                                             route=getattr(request.scope.get("route"), "path", "unmatched"))))
            return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})


def install_request_logging(application):
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    @application.middleware("http")
    async def correlate(request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", supplied) else str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(json.dumps(dict(event="request_complete", request_id=request_id,
                                    route=getattr(request.scope.get("route"), "path", "unmatched"),
                                    method=request.method, status=response.status_code,
                                    elapsed_ms=round((perf_counter() - started) * 1000, 3))))
        return response
