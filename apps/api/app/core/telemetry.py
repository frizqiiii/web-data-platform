"""OpenTelemetry wiring — NOT IMPLEMENTED.

This is a deliberate stub, not a fake implementation. Master Prompt
Section 1.5 forbids fake metrics/health/observability; rather than
wiring a no-op tracer and calling it "observability", this stays
unimplemented until Phase 12. Importing this module currently does
nothing and nothing calls it yet.
"""


def configure_telemetry() -> None:
    """No-op placeholder. Real tracer/exporter wiring lands in Phase 12."""
    return None
