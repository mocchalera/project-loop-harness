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
from .handoff_packet import (
    HANDOFF_PACKET_CONTRACT_VERSION,
    HandoffPacketValidationResult,
    compute_packet_id as compute_handoff_packet_id,
    finalize_handoff_packet,
    handoff_packet_schema,
    load_handoff_packet,
    validate_handoff_packet,
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
    "HANDOFF_PACKET_CONTRACT_VERSION",
    "HandoffPacketValidationResult",
    "compute_handoff_packet_id",
    "finalize_handoff_packet",
    "handoff_packet_schema",
    "load_handoff_packet",
    "validate_handoff_packet",
]
