from __future__ import annotations

from app.schemas.health import SourceStatus

TIDAL_STATUS = SourceStatus(
    available=False,
    reason=(
        "TIDAL acquisition unavailable: no supported lawful authenticated external downloader is "
        "configured; requires an operator-provided backend authorized for permanent local "
        "downloads "
        "with health, search, enqueue, status, cancellation, staging, and provenance support."
    ),
    details={
        "code": "backend_not_configured",
        "prerequisites": [
            "operator-confirmed rights for permanent local downloads",
            "authenticated live health and version negotiation",
            "search, enqueue, status, cancellation, staging, and provenance capabilities",
        ],
    },
)
