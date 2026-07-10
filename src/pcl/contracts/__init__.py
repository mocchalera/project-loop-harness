"""Stable, versioned artifact contracts exposed by Project Loop Harness."""

from .completion_packet import (
    COMPLETION_PACKET_CONTRACT_VERSION,
    CompletionPacketValidationResult,
    calculate_proof_level,
    canonical_json,
    completion_packet_schema,
    compute_packet_id,
    load_completion_packet,
    validate_completion_packet,
    with_computed_packet_id,
)

__all__ = [
    "COMPLETION_PACKET_CONTRACT_VERSION",
    "CompletionPacketValidationResult",
    "calculate_proof_level",
    "canonical_json",
    "completion_packet_schema",
    "compute_packet_id",
    "load_completion_packet",
    "validate_completion_packet",
    "with_computed_packet_id",
]
