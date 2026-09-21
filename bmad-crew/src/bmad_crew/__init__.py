"""BMAD crew rebuilt in CrewAI — see crew.py."""
__all__ = ["crew", "main", "server", "observability"]

# ---------------------------------------------------------------------------
# Early bootstrap — MUST run before any crewai module is imported.
#
# CrewAI instantiates its Telemetry singleton at *module import time* inside
# crewai/events/event_listener.py (line 854: `event_listener = EventListener()`).
# That singleton reads CREWAI_TELEMETRY_BASE_URL from crewai.telemetry.constants
# when building the OTLPSpanExporter.  If we want to capture what CrewAI would
# have sent to telemetry.crewai.com, we must:
#   1. Load .env before crewai modules run (crewai does this too, but later).
#   2. Patch the URL constant before the singleton is created.
#
# To enable:  set CREWAI_DISABLE_TELEMETRY=false in .env
# To disable: set CREWAI_DISABLE_TELEMETRY=true  in .env  (default)
# ---------------------------------------------------------------------------
import os as _os
from dotenv import load_dotenv as _load_dotenv

_load_dotenv()  # load .env now — crewai's own load_dotenv() will be a no-op after this

if _os.getenv("CREWAI_DISABLE_TELEMETRY", "true").lower() != "true":
    _endpoint = _os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if _endpoint:
        try:
            import crewai.telemetry.constants as _crewai_tc
            _original_url = _crewai_tc.CREWAI_TELEMETRY_BASE_URL
            _crewai_tc.CREWAI_TELEMETRY_BASE_URL = _endpoint
            print(
                f"[bmad-crew] CrewAI native telemetry redirected "
                f"{_original_url} → {_endpoint}"
            )
        except Exception:
            pass  # not installed or already patched — continue normally
