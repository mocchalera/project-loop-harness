from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
from typing import Any
import zlib

from .command_domain import _guard_feature_done
from .db import connect, connect_mutation
from .direct_spec import DirectSpecError, DirectSpecRootBinding, secure_read_project_artifact
from .errors import (
    EXIT_DATA_ERROR,
    EXIT_NOT_INITIALIZED,
    EXIT_RECOVERABLE_PENDING,
    EXIT_USAGE,
    ProjectionPendingError,
)
from .events import append_event
from .locks import project_operation_lock, require_live_exclusive_project_operation_capability
from .outbox import canonical_event_bytes, canonical_event_record
from .paths import ProjectPaths
from .prefixed_ids import decimal_sort_key, increment_decimal_text
from .project_config import dashboard_auto_render
from .renderer import _render_dashboard_with_lock
from .tasks import task_terminal_readiness_for_row
from .test_faults import crash_if_requested
from .timeutil import utc_now_iso
from .validators import collect_authoritative_admission_findings, validate_project


TASK_ACCEPT_CONTRACT_VERSION = "task-accept-envelope/v1"
TASK_ACCEPT_REQUEST_VERSION = "task-accept-request/v1"
TASK_ACCEPT_PREIMAGE_VERSION = "task-accept-bundle-preimage/v1"
TASK_ACCEPT_RECEIPT_VERSION = "task-acceptance-receipt/v1"
TASK_ACCEPT_MAX_ARTIFACT_BYTES = 10_000_000
TASK_ACCEPT_MAX_TESTS = 96
TASK_ACCEPT_MAX_PATH_BYTES = 4_096
TASK_ACCEPT_MAX_COMMAND_BYTES = 8_192
TASK_ACCEPT_MAX_SUMMARY_BYTES = 65_536
TASK_ACCEPT_MAX_EVENT_PAYLOAD_BYTES = 131_072
_TASK_ID = re.compile(r"^T-[0-9]{4,4096}$")
_TEST_ID = re.compile(r"^TC-[0-9]{4,4096}$")
_EVIDENCE_ID = re.compile(r"^E-([0-9]+)$")
_FRAME_NAME = re.compile(r"^(?P<role>[a-z][a-z0-9-]*)-(?P<digest>[0-9a-f]{64})\.json$")
_M2_RECORD_CONTENTS_FIXTURE_SHA256 = (
    "07e41045a685aac088ae6323352f8c5d5ecd2173a56fd1e2c23e49c878c64b0b"
)

_M2_DOMAINS = {
    "accepted": "task-accept-accepted-marker/v1",
    "begin": "task-accept-begin-marker/v1",
    "evidence-binding": "task-accept-evidence-binding/v1",
    "feature-binding": "task-accept-feature-binding/v1",
    "generation-manifest": "task-accept-generation-manifest/v2",
    "plan-binding": "task-accept-plan-binding/v1",
    "projection": "task-accept-projection-marker/v1",
    "render": "task-accept-render-marker/v1",
    "request-binding": "task-accept-request-binding/v1",
    "sqlite-commit": "task-accept-sqlite-commit-marker/v1",
    "tail": "task-accept-tail-marker/v1",
    "task-binding": "task-accept-task-binding/v1",
    "teardown": "task-accept-teardown-marker/v1",
    "test-binding": "task-accept-test-binding/v1",
    "ledger-reserved": "task-accept-generation-ledger-entry/v2",
    "ledger-sealed": "task-accept-generation-ledger-entry/v2",
    "ledger-advanced": "task-accept-generation-ledger-entry/v2",
    "event": "reservation-id-index-entry/v1",
    "evidence": "reservation-id-index-entry/v1",
    "outbox": "reservation-id-index-entry/v1",
    "reservation-manifest": "reservation-id-index-manifest/v2",
}

TASK_ACCEPT_ENVELOPE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": TASK_ACCEPT_CONTRACT_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "authority",
        "business_attempt_generation",
        "business_changed",
        "changed",
        "effects",
        "error_code",
        "exit_code",
        "identity",
        "message",
        "mode",
        "mutation_committed",
        "ok",
        "operation",
        "pending_tail",
        "phase",
        "prior_acceptance_verified",
        "prior_authoritative_commit",
        "receipts",
        "safe_retry_action",
        "safe_to_retry_original",
        "schema_version",
        "status",
        "tail_recovery_changed",
        "tail_recovery_generation",
        "teardown",
        "validation",
    ],
}

_EFFECT_KEYS = {
    "business_attempt_ledger_records_published",
    "business_db_rows_deleted",
    "business_db_rows_inserted",
    "business_db_rows_updated",
    "copies_published",
    "db_mutations_total",
    "durable_recovery_records_published",
    "events_appended",
    "evidence_links_inserted",
    "evidence_rows_inserted",
    "feature_status_updates",
    "generation_ledger_records_published",
    "live_generation_records_published",
    "markers_published",
    "outbox_records_appended",
    "projection_records_delivered",
    "render_writes",
    "reservation_index_records_published",
    "tail_db_rows_deleted",
    "tail_db_rows_inserted",
    "tail_db_rows_updated",
    "tail_recovery_ledger_records_published",
    "task_rows_updated",
    "teardown_receipts_published",
    "test_rows_updated",
}

_AUTHORITY_KEYS = {
    "acceptance_receipt_sha256",
    "event_id",
    "prior_authoritative_commit",
    "sequence",
    "state",
}
_IDENTITY_KEYS = {
    "artifact_locator_sha256",
    "feature_id",
    "plan_digest",
    "pre_accept_prefix_hwm",
    "pre_accept_prefix_sha256",
    "project_instance_id",
    "request_id",
    "request_locator",
    "task_id",
    "test_ids",
}
_PENDING_TAIL_KEYS = {
    "detail_sha256",
    "outbox_pending_count",
    "render_pending",
    "stage",
    "tail_marker_pending",
    "teardown_receipt_pending",
}
_RECEIPT_KEYS = {
    "acceptance_receipt_status",
    "directory_fixture_sha256",
    "generation_directory_status",
    "projection_status",
    "record_fixture_sha256",
    "render_status",
    "request_binding_status",
    "reservation_index_status",
    "sealed_head_frame_sha256",
    "sqlite_commit_status",
    "tail_marker_frame_sha256",
    "tail_status",
    "teardown_receipt_status",
}
_TEARDOWN_KEYS = {
    "lock_release_attempted",
    "lock_released",
    "raw_close_attempted",
    "raw_close_confirmed",
    "registry_invalidated",
    "registry_invalidation_attempted",
    "rollback_attempted",
    "rollback_confirmed",
    "status",
}
_VALIDATION_KEYS = {
    "current_proof_revalidated",
    "current_proof_status",
    "evaluated_hwm",
    "finding_count",
    "findings_sha256",
    "origin",
    "policy_registry_sha256",
    "status",
    "terminal_classification",
}
_MODE_STATUS = {
    "accepted_authority_tail_recovery_error": "error",
    "accepted_authority_tail_recovery_success": "recovered",
    "exact_replay_success": "no_op",
    "fresh_postcommit_tail_error": "error",
    "fresh_success": "success",
    "precommit_error": "error",
    "stale_precommit_generation_advanced": "retry_required",
}

TASK_ACCEPT_ENVELOPE_SCHEMA["properties"] = {
    "authority": {
        "$ref": "#/$defs/authority",
    },
    "business_attempt_generation": {"type": ["integer", "null"], "minimum": 0},
    "business_changed": {"type": "boolean"},
    "changed": {"type": "boolean"},
    "error_code": {
        "type": ["string", "null"],
        "pattern": r"^task_accept_[a-z0-9_]+$",
    },
    "exit_code": {"type": "integer", "enum": [0, 1, 2, 3, 4, 6]},
    "identity": {"$ref": "#/$defs/identity"},
    "message": {"type": "string", "minLength": 1, "maxLength": 4096},
    "mode": {"type": "string", "enum": sorted(_MODE_STATUS)},
    "mutation_committed": {"type": "boolean"},
    "ok": {"type": "boolean"},
    "operation": {"const": "task_accept"},
    "pending_tail": {"$ref": "#/$defs/pending_tail"},
    "phase": {
        "type": "string",
        "enum": [
            "phase0",
            "identity",
            "precommit",
            "business_commit",
            "projection",
            "render",
            "teardown",
            "tail_recovery",
            "complete",
        ],
    },
    "prior_acceptance_verified": {"type": "boolean"},
    "prior_authoritative_commit": {"type": "boolean"},
    "receipts": {"$ref": "#/$defs/receipts"},
    "safe_retry_action": {
        "enum": [
            None,
            "correct_input_then_retry",
            "repeat_exact_task_accept_request",
            "pcl audit flush --json",
            "pcl render --json",
            "manual_integrity_review",
            "process_restart_and_inspect",
        ]
    },
    "safe_to_retry_original": {"type": "boolean"},
    "schema_version": {"const": TASK_ACCEPT_CONTRACT_VERSION},
    "tail_recovery_changed": {"type": "boolean"},
    "tail_recovery_generation": {"type": ["integer", "null"], "minimum": 0},
    "teardown": {"$ref": "#/$defs/teardown"},
    "validation": {"$ref": "#/$defs/validation"},
    "status": {"type": "string", "enum": sorted(set(_MODE_STATUS.values()))},
    "effects": {"$ref": "#/$defs/effects"},
}

_DIGEST_SCHEMA = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
_DIGEST_OR_NULL_SCHEMA = {
    "anyOf": [{"type": "null"}, {"$ref": "#/$defs/digest"}]
}
TASK_ACCEPT_ENVELOPE_SCHEMA["$defs"] = {
    "digest": _DIGEST_SCHEMA,
    "digest_or_null": _DIGEST_OR_NULL_SCHEMA,
    "authority": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_AUTHORITY_KEYS),
        "properties": {
            "acceptance_receipt_sha256": {"$ref": "#/$defs/digest_or_null"},
            "event_id": {
                "type": ["string", "null"],
                "pattern": r"^EV-[A-Z][0-9]{11,}$",
            },
            "prior_authoritative_commit": {"type": "boolean"},
            "sequence": {"type": ["integer", "null"], "minimum": 1},
            "state": {
                "type": "string",
                "enum": ["not_established", "committed_current", "verified_prior"],
            },
        },
    },
    "effects": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_EFFECT_KEYS),
        "properties": {
            key: {"type": "integer", "minimum": 0} for key in _EFFECT_KEYS
        },
    },
    "identity": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_IDENTITY_KEYS),
        "properties": {
            "artifact_locator_sha256": {"$ref": "#/$defs/digest_or_null"},
            "feature_id": {
                "type": ["string", "null"],
                "pattern": r"^F-[0-9]{4,}$",
            },
            "plan_digest": {"$ref": "#/$defs/digest_or_null"},
            "pre_accept_prefix_hwm": {
                "type": ["integer", "null"],
                "minimum": 0,
            },
            "pre_accept_prefix_sha256": {"$ref": "#/$defs/digest_or_null"},
            "project_instance_id": {"$ref": "#/$defs/digest_or_null"},
            "request_id": {"$ref": "#/$defs/digest_or_null"},
            "request_locator": {"$ref": "#/$defs/digest_or_null"},
            "task_id": {
                "type": ["string", "null"],
                "pattern": r"^T-[0-9]{4,}$",
            },
            "test_ids": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": TASK_ACCEPT_MAX_TESTS,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": r"^TC-[0-9]{4,}$",
                        },
                    },
                ]
            },
        },
    },
    "pending_tail": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_PENDING_TAIL_KEYS),
        "properties": {
            "detail_sha256": {"$ref": "#/$defs/digest_or_null"},
            "outbox_pending_count": {"type": "integer", "minimum": 0},
            "render_pending": {"type": "boolean"},
            "stage": {
                "type": "string",
                "enum": ["none", "projection", "render", "teardown", "tail_seal", "corrupt"],
            },
            "tail_marker_pending": {"type": "boolean"},
            "teardown_receipt_pending": {"type": "boolean"},
        },
    },
    "receipts": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_RECEIPT_KEYS),
        "properties": {
            "acceptance_receipt_status": {
                "enum": ["not_started", "published", "prior_verified", "corrupt"]
            },
            "directory_fixture_sha256": {"$ref": "#/$defs/digest_or_null"},
            "generation_directory_status": {
                "enum": ["not_started", "partial", "published", "prior_verified", "recovered", "corrupt"]
            },
            "projection_status": {
                "enum": ["not_started", "pending", "delivered", "prior_delivered", "failed", "unknown"]
            },
            "record_fixture_sha256": {"$ref": "#/$defs/digest_or_null"},
            "render_status": {
                "enum": ["not_started", "pending", "current", "prior_current", "disabled", "failed", "unknown"]
            },
            "request_binding_status": {
                "enum": ["not_started", "published", "prior_verified", "corrupt"]
            },
            "reservation_index_status": {
                "enum": ["not_started", "published", "prior_verified", "corrupt"]
            },
            "sealed_head_frame_sha256": {"$ref": "#/$defs/digest_or_null"},
            "sqlite_commit_status": {
                "enum": ["not_started", "committed", "prior_committed", "unknown"]
            },
            "tail_marker_frame_sha256": {"$ref": "#/$defs/digest_or_null"},
            "tail_status": {
                "enum": ["not_started", "pending", "complete", "prior_complete", "corrupt", "unknown"]
            },
            "teardown_receipt_status": {
                "enum": ["not_started", "pending", "published", "prior_verified", "corrupt", "unknown"]
            },
        },
    },
    "teardown": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_TEARDOWN_KEYS),
        "properties": {
            "lock_release_attempted": {"type": "boolean"},
            "lock_released": {"type": ["boolean", "null"]},
            "raw_close_attempted": {"type": "boolean"},
            "raw_close_confirmed": {"type": ["boolean", "null"]},
            "registry_invalidated": {"type": ["boolean", "null"]},
            "registry_invalidation_attempted": {"type": "boolean"},
            "rollback_attempted": {"type": "boolean"},
            "rollback_confirmed": {"type": ["boolean", "null"]},
            "status": {
                "enum": ["not_started", "complete", "incomplete", "outcome_unknown"]
            },
        },
    },
    "validation": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_VALIDATION_KEYS),
        "properties": {
            "current_proof_revalidated": {"type": "boolean"},
            "current_proof_status": {
                "enum": ["not_evaluated", "healthy", "unhealthy", "unknown"]
            },
            "evaluated_hwm": {"type": ["integer", "null"], "minimum": 0},
            "finding_count": {"type": ["integer", "null"], "minimum": 0},
            "findings_sha256": {"$ref": "#/$defs/digest_or_null"},
            "origin": {
                "enum": [None, "fresh_commit_gate", "replay_live_revalidation", "tail_recovery_live_revalidation"]
            },
            "policy_registry_sha256": {"$ref": "#/$defs/digest_or_null"},
            "status": {"enum": ["not_evaluated", "passed", "blocked", "error"]},
            "terminal_classification": {
                "enum": [None, "ready", "ready_with_risk", "blocked"]
            },
        },
    },
}

_M5_GOLDENS_ZLIB_BASE64 = (
    "eNrtXFuTmzoS/isUz5laCSQB2afU1u4vSO3LqVNU6zbmBIMP4JlMbeW/b4uLwTY4zkwylwx5GYOEpG51t74v3fDH/3zYN5uyypoH/yNeKGV2DRTKpJVRJts1ab2BgAv/Y7HP8w++uTNFk2Z6uN5VWVmlwxjQZHcmVeV2mzX+Rwt5bT74tfl7b3DE4ZEau+GFX5RNavBC5lm9Mdr/9sGX+zorTF2n0DRmi5PfmsJUOGpZDE8fuqgNFLf42DDN6bWx1qimdlKdDZsbfWsqJ2JZ6Trd7Yc1fCSTGbRMq/Ie/5rcNEuNWVGbarF1v9MwNKpyl5nTybDjdt+0EtZpUzaQd7f3Feql3YTyzlQPC0ttdwPF2u1MoQ/3Mu3UneZZ8eVkfYe286VbA82+Mqnbnf2w8LptGjfhsuJyt/mTzvO9tlB9MdXp3XLfyPLr4ZEjiXZV+Rdu5XRI3BKcrOo7VK5vld6jBfZLrgyKdtctI8PGrwuLaSDLZ/f5qOFIUUct0/1tGw4bdlFTDdRfZgYwUOnyvhhc7+wp9JbTp9BpTFWhC6pSO6dqR+68ON3XcGvSttnHbl+zpu8VfPCdHTSD01dNZkGhW5QKGhzr2OUHy5g4fQ5FqrNbXM8YB8wwLf602dd0c79dbjyeod9gp+cu9oxTVS541M3MnX6xw+1W8LFX0z1Ud9eopS26JaqjV5HXLcdzg2VoLB40Xm6gbryyMN7NjXscdbbtlLpzu+hi2kGZg8/2sa6ZxJ3yy/hzdwhe043B5511Z8Vt6mzGbYE2rfUcq6X3iaGvKvdFM7X3vmEMtE0nYIEy+L09dt521vXU1E46oL52G6hb2d1f4h8i/XhAoJlnNptIfsVZMFj20lnTBp/+bMCL1ukwGuIWKdzrhxRtp4tSR4qaxJyx68JYk2Cy0KNz2YWpetUvPtrZpsy6LVvsdhqdFjrWBjCOpBsDuJ4Ktqerqf/OMeT1Sl4aZGoHc4N0lrfw7KmdzPZDc6nBum1sUPGgepNHNVadW+/2TdpsTNH18PvuTdk/geZymxXu6BssWW3MFpyF1aP33HQGc2OKO5Oja/3jjvodmmgXNLjmcRg+RQXHrefwYhDYGShGGIzSxsUFM0CHyVDT5jE6wX2q8nL2gbFNlYXNqu3kMXOb1U4VWXEHedZH96U2Zzczw5d5LgHXdKHpbOKl/RxncppQe9zJwkXvsrQo82SNA/o66nE0quu9h86eDr+nx4PNjgLc0c36NCa2pnI4OMo8Uw4c9Ro68Y6lVTSm2jp7w92AusYgpiY28O3bh+tBsZ+EUijQRlFmVMi5QTUHkYiFNBFlXEYUTMICJQMrmeRJBIYGjNFIR5QKGflTSO3/+783n8jhn/B/EF9TIkZ4fTiZ0n5vvguwyRy6bqr9FFx3l4/D1sHjsTWNLoFrPgeu6Ty4DuLr0HVIZ+C1uACv2TK8psvwOrgSXgdXwWvKZ/G1k2URYIvvAWxxBrDplQCbsp+IsMVTETb9DsKmswg7OEHYPQ0ewTS5Ekz7klNCE54kWoSB4mECVDPQgdaUKisgIEprSwMS6SRgoeFGRYG2EGP8iZji/jEU9/9zgzHCBZAjOO4rCAMQXNEgBCJ4IombluEECojh2gSGgIptEgqghFiVQKxxTYJpoRh0UG8WzGPvS1jex+E0xCxSNk5CKkAqSmQEoYg0RcF4GEupEhEKRWwQRFZFwgBB8SObxCpm/gIT8OGJ//xjHuFbFN/wiIHlwFF0GXFrGSRAcNmUW50QXHjEMZ4nSRyE3IYRi11bkOgwmSK9AwvxNRWaJBRVkTAM8lwnEUobCRHjEUAZ5THexO0PjNXM4tkQKlSQjBg1nIAR/oTD+J9xb1ngT3nMH/7nf7kdD/Fu+4tS/88jYvPZEZvuyZ7fGI3Eptzi+ZbnDyOfsei9m7TeY5+6XmAzXaB3ZKb/9RtwGRRv5wLQc7OZMchc4jJ+IjlEArQiVGrOWtOlUWiVSqgSeCsOYqFDmQTCGoYOw4Chm6FTc8ascmj4MhOarmOOB41Bf5EF+SQyjBLGQcQcQJE4RtsNgzDkgY0V1xi1dICrBi6spiZQQWhYouIoVoJJIv1zDjXgkwv8abryC+xp2m2ZO/lcBkxhEAq5iRGaScUwTgZKR9pYzoTSIUpEOOANogIDhsWago2YBiu1jf1F5jU60CXe5UvgEBtDbRgLxImKJABhpCCIQylJGErOuAUJCY01RGGsGa4s1FICatfGB4+YzjtY9jJlG7UzT9h61PzzqdkYaR5Lzsh1zKwLVSfErLs5S8xOmyb0qG+a5WVLbSe8rO/2JFp22Ngf4WQ9Zp+nZOgQebN5OCdjlPAzLkZmiJjPLJ5dGmisAglAFAk5k5LbBEKjJOIWTQOQTOOBRyXEUagCS6k7PUkgE+aAzEDj+qOod6Nb6GLzAqvzCQ2o4AFQibElIgIPXGUY4gv0JBpBlCDkAZrgEU6klJqySBAEFxHHZUoa2KlN7pD5XSaDuMGgH/y3wwe7bV+gg8P5lrYjPI4LrpmWNdOyZlpWHrjywDfGA50KPcjbA80bToJ/ekXpdbG8Hrmh+eqMtjJoTA/foYiThNd744idvN8/jK9miO1Ih/FfmCaeLmaOK3adXogxdpNfwxtPRblEHk/7vgiD7EV7IR55mP0KNnmsrmemlEWZlruVUC60nE37MnxSPD+f7A+uFiAfZHASrrTyvaQZ6atIMwbXUcuAv6o0I70uzThPLp0sj08zPp5d/tQ0I/nVaUZyVZrxqJBvorgBtx5RT7FSz5V6vjrqeQ/1IQ35wZP7xhvt2MtqbzTlo7TkrqybHhS3jnip5HJMUj614hJBCDWR40iI6NExjMGD0QhmOBVo+SIRAm0nFoEVcUSYSEgYQyJtCBEVNhQtCJnlr+Kcvx4w2W1XXTpoZYnEdv2XOaxrn5ZsTgd8hYnOa4o2dy6I4UG6QD4PpvNDxZrTx54j0XixSPM6ijdXojmKcYGd9X0WSjN3Kvdgr7PGs/m+3ng3N3/Vrbm8wsLMNfe35v5Wkvbacn9PYWivIfUnruNn4lWl/q6jZ/NFoOIpqb/H14CSlykBpY9K/dE19bfyr7fMvz4NZZ9TIuZ8xut9pj32er41kLPDkfKQHrvXmv57j+m/qaW8sSrRNdv3G1WNTu1wgTv2/zGySB3pmuX7LbN8Jyjw90r2vfiHNuiv5n/07ZR+0jfI/+azc3Qt/fwVH9m44Ekp6Dvn4XrN1q1s8VWyRa8w995gwV5vwd5owW0Or3NzVy9amR3ak9dsjNeWiXq9UCOlxE3AgDp+L2XeGd7R11MGTbzlD6hczsWtH0/5JR9P6Xwt7cqxpwfO6HNLnKsnA4+iXE0Lg9qPIuk1Z/c8xOt9f0LlxenO+qrb+qrbyneu5TuHtQwcJnWf+dq3uGxCcthKclaS83pKEj8Nn3vsjNcbbNPVIY72+1Kfe/RDQq3RMgmJjbUhVtiIoX2ATYzQnBiF7mCtDEzIiBCUJjRUNCECPQCkYYn/eLozSv9zGM/B698w4Rl18jKEZ5z/NZOdieU8hehsodgjjsyKxty2OWjExpm5X2sRV16zfhpyLQdc00FrOujp9Ig+Fz1aX9VaedEbLhWsEFGhNod3s7yjV4muLRt8Ltb0Dl/ZesHCw1f91tavKfy7SJ1+pHTv93+La63EWyvx3kYl3p//By3Arvo="
)


def task_accept_envelope_golden_fixtures() -> list[dict[str, Any]]:
    raw = zlib.decompress(base64.b64decode(_M5_GOLDENS_ZLIB_BASE64))
    values = json.loads(raw)
    if not isinstance(values, list) or len(values) != 8 or any(not isinstance(value, dict) for value in values):
        raise RuntimeError("embedded Task Accept M5 goldens are corrupt")
    for value in values:
        validate_task_accept_envelope(value)
    return values


@dataclass
class _Abort(Exception):
    code: str
    message: str
    exit_code: int = 1
    phase: str = "precommit"
    safe_to_retry_original: bool = False
    prior_acceptance_verified: bool = False
    safe_retry_action: str | None = None


@dataclass
class _GenerationAdvanced(Exception):
    generation: int
    identity: dict[str, Any]


@dataclass(frozen=True)
class _Artifact:
    relative_path: str
    content: bytes
    sha256: str
    size_bytes: int
    root_binding: DirectSpecRootBinding


@dataclass(frozen=True)
class _Generation:
    number: int
    directory: Path
    record: dict[str, Any]
    record_sha256: str
    created: bool


@dataclass(frozen=True)
class _LedgerState:
    generations: tuple[_Generation, ...]
    accepted_count: int
    tail_recovery_generation: int


@dataclass
class _RetainedProofFile:
    paths: ProjectPaths
    relative_path: str
    descriptors: tuple[int, ...]
    root_fd: int
    parent_fd: int
    leaf_fd: int
    leaf_name: str
    root_identity: tuple[int, int, int]
    directory_links: tuple[tuple[int, str, tuple[int, int, int]], ...]
    leaf_identity: tuple[int, int, int, int, int, int]
    content: bytes
    _closed: bool = False

    def verify(self) -> None:
        if self._closed:
            raise _Abort(
                "task_accept_current_proof_invalid",
                "The retained current acceptance proof descriptor is closed.",
                EXIT_DATA_ERROR,
                "final_reseal",
            )
        try:
            held_root = os.fstat(self.root_fd)
            current_root = os.stat(self.paths.root, follow_symlinks=False)
            held_leaf = os.fstat(self.leaf_fd)
            current_leaf = os.stat(
                self.leaf_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            current_content = _read_retained_descriptor(self.leaf_fd)
            directory_matches = all(
                _proof_directory_identity(
                    os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
                )
                == expected
                for parent_fd, component, expected in self.directory_links
            )
        except OSError as exc:
            raise _Abort(
                "task_accept_current_proof_invalid",
                "The retained current acceptance proof could not be resealed.",
                EXIT_DATA_ERROR,
                "final_reseal",
            ) from exc
        if (
            _proof_directory_identity(held_root) != self.root_identity
            or _proof_directory_identity(current_root) != self.root_identity
            or _proof_file_identity(held_leaf) != self.leaf_identity
            or _proof_file_identity(current_leaf) != self.leaf_identity
            or current_content != self.content
            or not directory_matches
        ):
            raise _Abort(
                "task_accept_current_proof_invalid",
                "The retained current acceptance proof changed before SQLite commit.",
                EXIT_DATA_ERROR,
                "final_reseal",
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass
class _RetainedProofSeal:
    files: tuple[_RetainedProofFile, ...]

    def verify(self) -> None:
        for retained in self.files:
            retained.verify()

    def close(self) -> None:
        for retained in self.files:
            retained.close()


def canonical_task_accept_json(payload: dict[str, Any]) -> str:
    try:
        validate_task_accept_envelope(payload)
        value = payload
    except (TypeError, ValueError):
        value = _internal_serialization_envelope()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_task_accept_envelope(payload: dict[str, Any]) -> None:
    required = set(TASK_ACCEPT_ENVELOPE_SCHEMA["required"])
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("task accept envelope top-level schema mismatch")
    _validate_task_accept_schema_value(
        payload,
        TASK_ACCEPT_ENVELOPE_SCHEMA,
        root=TASK_ACCEPT_ENVELOPE_SCHEMA,
        path="$",
    )
    if payload["schema_version"] != TASK_ACCEPT_CONTRACT_VERSION:
        raise ValueError("task accept envelope version mismatch")
    boolean_fields = (
        "business_changed",
        "changed",
        "mutation_committed",
        "ok",
        "prior_acceptance_verified",
        "prior_authoritative_commit",
        "safe_to_retry_original",
        "tail_recovery_changed",
    )
    if (
        payload["operation"] != "task_accept"
        or any(type(payload[key]) is not bool for key in boolean_fields)
        or type(payload["exit_code"]) is not int
        or payload["exit_code"] not in {0, 1, 2, 3, 4, 6}
        or not isinstance(payload["message"], str)
        or payload["error_code"] is not None
        and not isinstance(payload["error_code"], str)
        or payload["safe_retry_action"] is not None
        and not isinstance(payload["safe_retry_action"], str)
    ):
        raise ValueError("task accept envelope boolean contract mismatch")
    if _MODE_STATUS.get(payload["mode"]) != payload["status"]:
        raise ValueError("task accept envelope mode/status mismatch")
    if set(payload["effects"]) != _EFFECT_KEYS or any(
        type(value) is not int or value < 0 for value in payload["effects"].values()
    ):
        raise ValueError("task accept effect schema mismatch")
    effects = payload["effects"]
    if effects["business_db_rows_inserted"] != (
        effects["evidence_rows_inserted"]
        + effects["evidence_links_inserted"]
        + effects["events_appended"]
        + effects["outbox_records_appended"]
    ):
        raise ValueError("task accept inserted-row accounting mismatch")
    if effects["business_db_rows_updated"] != (
        effects["test_rows_updated"]
        + effects["feature_status_updates"]
        + effects["task_rows_updated"]
    ):
        raise ValueError("task accept updated-row accounting mismatch")
    if effects["db_mutations_total"] != (
        effects["business_db_rows_inserted"]
        + effects["business_db_rows_updated"]
        + effects["business_db_rows_deleted"]
        + effects["tail_db_rows_inserted"]
        + effects["tail_db_rows_updated"]
        + effects["tail_db_rows_deleted"]
    ):
        raise ValueError("task accept DB accounting mismatch")
    if effects["generation_ledger_records_published"] != (
        effects["business_attempt_ledger_records_published"]
        + effects["tail_recovery_ledger_records_published"]
    ):
        raise ValueError("task accept generation accounting mismatch")
    if effects["markers_published"] != (
        effects["reservation_index_records_published"]
        + effects["live_generation_records_published"]
        + effects["generation_ledger_records_published"]
    ):
        raise ValueError("task accept marker accounting mismatch")
    if effects["durable_recovery_records_published"] != effects["markers_published"]:
        raise ValueError("task accept durable record accounting mismatch")
    if bool(payload["ok"]) != (payload["exit_code"] == 0 and payload["error_code"] is None):
        raise ValueError("task accept status/exit accounting mismatch")
    if payload["mode"] == "fresh_success" and payload["mutation_committed"] is not True:
        raise ValueError("fresh success must confirm a committed mutation")
    if (
        payload["mode"] == "fresh_postcommit_tail_error"
        and payload["error_code"] != "task_accept_commit_outcome_unknown"
        and payload["mutation_committed"] is not True
    ):
        raise ValueError("known postcommit failure must confirm a committed mutation")
    if (
        payload["mode"] not in {"fresh_success", "fresh_postcommit_tail_error"}
        and payload["mutation_committed"] is not False
    ):
        raise ValueError("non-fresh envelopes cannot report a committed mutation")
    if payload["changed"] != (
        payload["business_changed"]
        or payload["tail_recovery_changed"]
        or effects["markers_published"] > 0
    ):
        raise ValueError("task accept changed accounting mismatch")
    _validate_task_accept_semantics(payload)


def _validate_task_accept_schema_value(
    value: Any,
    schema: dict[str, Any],
    *,
    root: dict[str, Any],
    path: str,
) -> None:
    reference = schema.get("$ref")
    if reference is not None:
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise ValueError(f"unsupported Task Accept schema reference at {path}")
        target = root.get("$defs", {}).get(reference.removeprefix(prefix))
        if not isinstance(target, dict):
            raise ValueError(f"missing Task Accept schema reference at {path}")
        _validate_task_accept_schema_value(value, target, root=root, path=path)
        return
    alternatives = schema.get("anyOf")
    if alternatives is not None:
        if not isinstance(alternatives, list):
            raise ValueError(f"invalid Task Accept anyOf schema at {path}")
        for alternative in alternatives:
            try:
                _validate_task_accept_schema_value(
                    value,
                    alternative,
                    root=root,
                    path=path,
                )
            except ValueError:
                continue
            return
        raise ValueError(f"Task Accept schema anyOf mismatch at {path}")
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(allowed, list) or not any(
            _task_accept_json_type_matches(value, item) for item in allowed
        ):
            raise ValueError(f"Task Accept schema type mismatch at {path}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"Task Accept schema const mismatch at {path}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Task Accept schema enum mismatch at {path}")
    if isinstance(value, dict):
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            raise ValueError(f"invalid Task Accept object schema at {path}")
        missing = set(required) - set(value)
        if missing:
            raise ValueError(f"Task Accept schema required mismatch at {path}")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(f"Task Accept schema additional property at {path}")
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _validate_task_accept_schema_value(
                    item,
                    child,
                    root=root,
                    path=f"{path}.{key}",
                )
    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"Task Accept schema array too short at {path}")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ValueError(f"Task Accept schema array too long at {path}")
        if schema.get("uniqueItems") and len({_canonical_bytes(item) for item in value}) != len(value):
            raise ValueError(f"Task Accept schema array duplicates at {path}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_task_accept_schema_value(
                    item,
                    item_schema,
                    root=root,
                    path=f"{path}[{index}]",
                )
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise ValueError(f"Task Accept schema string too short at {path}")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            raise ValueError(f"Task Accept schema string too long at {path}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ValueError(f"Task Accept schema pattern mismatch at {path}")
    if type(value) is int:
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            raise ValueError(f"Task Accept schema minimum mismatch at {path}")


def _task_accept_json_type_matches(value: Any, expected: Any) -> bool:
    return {
        "array": isinstance(value, list),
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "null": value is None,
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }.get(expected, False)


def _validate_task_accept_semantics(payload: dict[str, Any]) -> None:
    authority = payload["authority"]
    identity = payload["identity"]
    pending = payload["pending_tail"]
    teardown = payload["teardown"]
    validation = payload["validation"]
    mode = payload["mode"]
    phase = payload["phase"]

    established = authority["state"] != "not_established"
    authority_values = (
        authority["acceptance_receipt_sha256"],
        authority["event_id"],
        authority["sequence"],
    )
    if established != all(value is not None for value in authority_values):
        raise ValueError("task accept authority establishment mismatch")
    if authority["state"] == "not_established" and any(
        value is not None for value in authority_values
    ):
        raise ValueError("task accept unestablished authority is populated")
    expected_prior = authority["state"] == "verified_prior"
    if (
        authority["prior_authoritative_commit"] != payload["prior_authoritative_commit"]
        or authority["prior_authoritative_commit"] != expected_prior
        or payload["prior_acceptance_verified"] != expected_prior
    ):
        raise ValueError("task accept prior-authority mismatch")

    identity_values = list(identity.values())
    identity_full = all(value is not None for value in identity_values)
    identity_empty = all(value is None for value in identity_values)
    if phase == "phase0" and not identity_empty:
        raise ValueError("task accept phase0 identity must be empty")
    if phase in {"precommit", "business_commit", "projection", "render", "teardown", "tail_recovery", "complete"} and not identity_full:
        raise ValueError("task accept phase requires a complete identity")
    if established and not identity_full:
        raise ValueError("task accept authority requires a complete identity")
    if phase == "phase0" and (
        payload["business_attempt_generation"] is not None
        or payload["tail_recovery_generation"] is not None
        or any(payload["effects"].values())
        or payload["receipts"] != _empty_receipts()
        or teardown["status"] != "not_started"
    ):
        raise ValueError("task accept phase0 authority is not empty")
    if phase == "identity" and (established or validation["status"] != "not_evaluated"):
        raise ValueError("task accept identity phase established authority early")
    if phase == "precommit" and identity_full and (
        payload["business_attempt_generation"] is None
        or payload["tail_recovery_generation"] is None
        or established
    ):
        raise ValueError("task accept precommit authority mismatch")

    if pending["stage"] == "none":
        if (
            pending["detail_sha256"] is not None
            or pending["outbox_pending_count"] != 0
            or pending["render_pending"]
            or pending["tail_marker_pending"]
            or pending["teardown_receipt_pending"]
        ):
            raise ValueError("task accept empty pending-tail mismatch")
    elif pending["detail_sha256"] is None:
        raise ValueError("task accept pending-tail detail is missing")

    if validation["status"] == "not_evaluated":
        if (
            validation["current_proof_revalidated"]
            or validation["current_proof_status"] != "not_evaluated"
            or validation["evaluated_hwm"] is not None
            or validation["finding_count"] is not None
            or validation["findings_sha256"] is not None
            or validation["origin"] is not None
            or validation["policy_registry_sha256"] is not None
            or validation["terminal_classification"] is not None
        ):
            raise ValueError("task accept unevaluated validation mismatch")
    else:
        if (
            validation["evaluated_hwm"] is None
            or validation["finding_count"] is None
            or validation["findings_sha256"] is None
            or validation["origin"] is None
            or validation["policy_registry_sha256"] is None
            or validation["terminal_classification"] is None
        ):
            raise ValueError("task accept evaluated validation is incomplete")
        if validation["status"] == "passed" and (
            not validation["current_proof_revalidated"]
            or validation["current_proof_status"] != "healthy"
            or validation["terminal_classification"] not in {"ready", "ready_with_risk"}
        ):
            raise ValueError("task accept passed validation mismatch")
        if validation["status"] == "blocked" and validation["terminal_classification"] != "blocked":
            raise ValueError("task accept blocked validation mismatch")

    if teardown["status"] == "not_started":
        if any(
            teardown[key]
            for key in (
                "lock_release_attempted",
                "raw_close_attempted",
                "registry_invalidation_attempted",
                "rollback_attempted",
            )
        ) or any(
            teardown[key] is not None
            for key in (
                "lock_released",
                "raw_close_confirmed",
                "registry_invalidated",
                "rollback_confirmed",
            )
        ):
            raise ValueError("task accept unstarted teardown mismatch")
    if teardown["status"] == "complete":
        if not all(
            teardown[key] is True
            for key in (
                "lock_release_attempted",
                "lock_released",
                "raw_close_attempted",
                "raw_close_confirmed",
                "registry_invalidation_attempted",
                "registry_invalidated",
            )
        ):
            raise ValueError("task accept completed teardown is unconfirmed")
        if teardown["rollback_attempted"] != (teardown["rollback_confirmed"] is True):
            raise ValueError("task accept rollback confirmation mismatch")

    if mode == "precommit_error":
        if (
            payload["exit_code"] not in {1, 2, 3, 4}
            or payload["mutation_committed"]
            or payload["business_changed"]
            or payload["tail_recovery_changed"]
            or established
        ):
            raise ValueError("task accept precommit mode mismatch")
    elif mode == "fresh_success":
        if (
            phase != "complete"
            or not payload["mutation_committed"]
            or expected_prior
            or authority["state"] != "committed_current"
            or payload["business_attempt_generation"] != 0
            or payload["tail_recovery_generation"] != 0
            or not payload["business_changed"]
            or payload["tail_recovery_changed"]
            or validation["status"] != "passed"
            or payload["receipts"]["tail_status"] != "complete"
            or payload["receipts"]["generation_directory_status"] != "published"
        ):
            raise ValueError("task accept fresh-success mode mismatch")
    elif mode == "exact_replay_success":
        if (
            phase != "complete"
            or payload["mutation_committed"]
            or not expected_prior
            or any(payload["effects"].values())
            or payload["business_attempt_generation"] != 0
            or payload["tail_recovery_generation"] is None
            or payload["business_changed"]
            or payload["tail_recovery_changed"]
            or validation["status"] != "passed"
            or payload["receipts"]["tail_status"] != "prior_complete"
        ):
            raise ValueError("task accept replay mode mismatch")
    elif mode == "accepted_authority_tail_recovery_success":
        if (
            phase != "complete"
            or payload["mutation_committed"]
            or not expected_prior
            or payload["business_attempt_generation"] != 0
            or payload["tail_recovery_generation"] is None
            or payload["tail_recovery_generation"] < 1
            or payload["business_changed"]
            or not payload["tail_recovery_changed"]
            or validation["status"] != "passed"
            or payload["receipts"]["generation_directory_status"] != "recovered"
            or payload["receipts"]["tail_status"] != "complete"
        ):
            raise ValueError("task accept recovery-success mode mismatch")
    elif mode == "accepted_authority_tail_recovery_error":
        if (
            payload["exit_code"] != 6
            or payload["mutation_committed"]
            or not expected_prior
            or payload["business_changed"]
        ):
            raise ValueError("task accept recovery-error mode mismatch")
    elif mode == "stale_precommit_generation_advanced":
        if (
            phase != "precommit"
            or payload["exit_code"] != 6
            or payload["mutation_committed"]
            or not payload["safe_to_retry_original"]
            or payload["safe_retry_action"] != "repeat_exact_task_accept_request"
        ):
            raise ValueError("task accept stale-generation mode mismatch")
    elif mode == "fresh_postcommit_tail_error" and (
        payload["exit_code"] != 6
        or expected_prior
        or payload["tail_recovery_changed"]
        or (
            payload["error_code"] != "task_accept_commit_outcome_unknown"
            and (
                not established
                or authority["state"] != "committed_current"
                or not payload["business_changed"]
            )
        )
    ):
        raise ValueError("task accept fresh-tail-error mode mismatch")

    if payload["safe_to_retry_original"] != (
        mode == "stale_precommit_generation_advanced"
    ):
        raise ValueError("task accept original-retry authority mismatch")


def task_accept_human_line(payload: dict[str, Any]) -> str:
    validate_task_accept_envelope(payload)
    if payload["ok"]:
        authority = payload["authority"]
        return (
            f"OK task_accept {payload['mode']}: {payload['message']} "
            f"[authority={authority['event_id']}@{authority['sequence']}]"
        )
    action = payload["safe_retry_action"]
    suffix = "" if action is None else f" [action={action}]"
    return f"ERROR task_accept {payload['error_code']}: {payload['message']}{suffix}"


def accept_task(
    paths: ProjectPaths,
    *,
    task_id: str,
    artifact_path: str,
    command: str,
    summary: str,
    copy_files: bool,
    test_ids: list[str],
) -> dict[str, Any]:
    """Atomically accept one Task through the fixed P1-B surface."""

    envelope = _envelope()
    envelope["mode"] = "fresh"
    artifact: _Artifact | None = None
    try:
        normalized = _validate_request_inputs(
            task_id=task_id,
            artifact_path=artifact_path,
            command=command,
            summary=summary,
            copy_files=copy_files,
            test_ids=test_ids,
        )
        if not paths.loop_dir.is_dir() or not paths.db_path.is_file():
            raise _Abort(
                "task_accept_not_initialized",
                "Project Loop Harness is not initialized at the requested root.",
                EXIT_NOT_INITIALIZED,
                "installation",
                True,
            )
        artifact = _read_artifact(paths, normalized["artifact_path"])
        envelope["phase"] = "artifact_preflight"
        result = _accept_under_root_binding(
            paths,
            artifact=artifact,
            task_id=normalized["task_id"],
            command=normalized["command"],
            summary=normalized["summary"],
            test_ids=normalized["test_ids"],
        )
        return result
    except _Abort as exc:
        return _error_envelope(
            envelope,
            code=exc.code,
            message=exc.message,
            exit_code=exc.exit_code,
            phase=exc.phase,
            safe_to_retry_original=exc.safe_to_retry_original,
            prior_acceptance_verified=exc.prior_acceptance_verified,
            safe_retry_action=exc.safe_retry_action,
        )
    except DirectSpecError:
        return _error_envelope(
            envelope,
            code="task_accept_artifact_preflight_failed",
            message="The acceptance artifact could not be read safely.",
            exit_code=EXIT_USAGE,
            phase="artifact_preflight",
            safe_to_retry_original=True,
        )
    except Exception:
        return _error_envelope(
            envelope,
            code="task_accept_internal_error",
            message="Atomic Task Accept failed before a commit could be confirmed.",
            exit_code=EXIT_DATA_ERROR,
            phase=str(envelope.get("phase") or "internal"),
            safe_to_retry_original=False,
        )
    finally:
        if artifact is not None:
            artifact.root_binding.close()


def _validate_request_inputs(
    *,
    task_id: str,
    artifact_path: str,
    command: str,
    summary: str,
    copy_files: bool,
    test_ids: list[str],
) -> dict[str, Any]:
    if not copy_files:
        raise _Abort(
            "task_accept_copy_required",
            "Atomic Task Accept requires --copy.",
            EXIT_USAGE,
            "input",
            True,
        )
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise _Abort(
            "task_accept_invalid_input",
            "Task ID must match T- followed by 4 to 4096 ASCII digits.",
            EXIT_USAGE,
            "input",
            True,
        )
    if not isinstance(test_ids, list) or not test_ids:
        raise _Abort(
            "task_accept_usage_error",
            "task accept requires at least one --test",
            EXIT_USAGE,
            "input",
            True,
        )
    if len(test_ids) > TASK_ACCEPT_MAX_TESTS:
        raise _Abort(
            "task_accept_invalid_input",
            f"Atomic Task Accept supports at most {TASK_ACCEPT_MAX_TESTS} Tests.",
            EXIT_USAGE,
            "input",
            True,
        )
    if any(not isinstance(value, str) or _TEST_ID.fullmatch(value) is None for value in test_ids):
        raise _Abort(
            "task_accept_invalid_input",
            "Every --test value must match TC- followed by 4 to 4096 ASCII digits.",
            EXIT_USAGE,
            "input",
            True,
        )
    if len(set(test_ids)) != len(test_ids):
        raise _Abort(
            "task_accept_invalid_input",
            "Duplicate --test values are not allowed.",
            EXIT_USAGE,
            "input",
            True,
        )
    normalized_path = _normalize_relative_path(artifact_path)
    command = _bounded_nonempty_utf8(command, "command", TASK_ACCEPT_MAX_COMMAND_BYTES)
    summary = _bounded_nonempty_utf8(summary, "summary", TASK_ACCEPT_MAX_SUMMARY_BYTES)
    return {
        "task_id": task_id,
        "test_ids": sorted(test_ids, key=_prefixed_id_sort_key),
        "artifact_path": normalized_path,
        "command": command,
        "summary": summary,
    }


def _normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise _Abort(
            "task_accept_invalid_input",
            "--artifact must be a non-empty project-relative path.",
            EXIT_USAGE,
            "input",
            True,
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _Abort(
            "task_accept_invalid_input",
            "--artifact must be valid UTF-8.",
            EXIT_USAGE,
            "input",
            True,
        ) from exc
    path = PurePosixPath(value)
    if (
        len(encoded) > TASK_ACCEPT_MAX_PATH_BYTES
        or path.is_absolute()
        or value != path.as_posix()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\x00" in value
    ):
        raise _Abort(
            "task_accept_invalid_input",
            "--artifact must be a normalized project-relative POSIX path.",
            EXIT_USAGE,
            "input",
            True,
        )
    return value


def _bounded_nonempty_utf8(value: str, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Abort(
            "task_accept_invalid_input",
            f"--{field} must not be empty.",
            EXIT_USAGE,
            "input",
            True,
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _Abort(
            "task_accept_invalid_input",
            f"--{field} must be valid UTF-8.",
            EXIT_USAGE,
            "input",
            True,
        ) from exc
    if len(encoded) > limit:
        raise _Abort(
            "task_accept_invalid_input",
            f"--{field} exceeds the {limit}-byte limit.",
            EXIT_USAGE,
            "input",
            True,
        )
    return value.strip()


def _read_artifact(paths: ProjectPaths, relative_path: str) -> _Artifact:
    content, binding = secure_read_project_artifact(
        paths,
        relative_path,
        max_bytes=TASK_ACCEPT_MAX_ARTIFACT_BYTES,
    )
    return _Artifact(
        relative_path=relative_path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        root_binding=binding,
    )


def _accept_under_root_binding(
    original_paths: ProjectPaths,
    *,
    artifact: _Artifact,
    task_id: str,
    command: str,
    summary: str,
    test_ids: list[str],
) -> dict[str, Any]:
    if not artifact.root_binding.current_matches(original_paths):
        raise _Abort(
            "task_accept_root_changed",
            "The project root changed after artifact preflight.",
            EXIT_DATA_ERROR,
            "root_binding",
        )
    paths = artifact.root_binding.bound_paths()
    result: dict[str, Any] | None = None
    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        require_live_exclusive_project_operation_capability(
            capability,
            loop_dir=paths.loop_dir,
        )
        _verify_artifact_again(paths, artifact)
        result = _accept_locked(
            paths,
            operation_capability=capability,
            artifact=artifact,
            task_id=task_id,
            command=command,
            summary=summary,
            test_ids=test_ids,
        )
    assert result is not None
    return result


def _accept_locked(
    paths: ProjectPaths,
    *,
    operation_capability: object,
    artifact: _Artifact,
    task_id: str,
    command: str,
    summary: str,
    test_ids: list[str],
) -> dict[str, Any]:
    conn = connect_mutation(
        paths,
        exclusive=True,
        operation_capability=operation_capability,
    )
    committed = False
    envelope = _envelope()
    envelope["mode"] = "fresh"
    try:
        now = utc_now_iso()
        admission = collect_authoritative_admission_findings(conn, now=now)
        if not admission.ok:
            raise _Abort(
                "task_accept_admission_failed",
                "Authoritative project admission checks failed.",
                1,
                "admission",
            )
        _require_delivered_outbox(conn)
        prefix = _verified_common_prefix(paths, conn)
        project_instance_id = _project_instance_id(conn)
        graph = _load_graph(conn, task_id=task_id, test_ids=test_ids)
        request, identity = _request_identity(
            project_instance_id=project_instance_id,
            artifact=artifact,
            task_id=task_id,
            feature_id=graph["feature_id"],
            test_ids=test_ids,
            command=command,
            summary=summary,
        )
        envelope["identity"] = _public_identity(identity)
        authority_event_id = _authority_event_id(request)
        _require_no_locator_drift(paths, identity)
        existing_authority = conn.execute(
            "SELECT id, sequence, payload_json FROM events WHERE id = ?",
            (authority_event_id,),
        ).fetchone()
        task_accept_events = _task_accept_authority_events(conn, task_id)
        if existing_authority is not None:
            conn.rollback()
            return _verified_replay(
                paths,
                operation_capability=operation_capability,
                request=request,
                identity=identity,
                graph=graph,
                authority_row=existing_authority,
                task_accept_events=task_accept_events,
            )
        if task_accept_events or str(graph["task"]["status"]) == "done":
            raise _Abort(
                "task_accept_task_request_conflict",
                "Task was accepted by a different request.",
                1,
                "request_route",
            )
        _require_fresh_eligibility(graph, test_ids=test_ids)
        generation, evidence_id, fs_effects = _prepare_durable_attempt(
            paths,
            conn,
            request=request,
            identity=identity,
            prefix=prefix,
            artifact=artifact,
        )
        envelope["business_attempt_generation"] = generation.number
        event_plan = _build_event_plan(
            conn,
            request_id=str(identity["request_id"]),
            authority_event_id=authority_event_id,
            evidence_id=evidence_id,
            feature_id=str(graph["feature_id"]),
            task_id=task_id,
            test_ids=test_ids,
            include_passing_event=str(graph["feature"]["status"]) != "passing",
        )
        structural_plan = _m2_structural_plan(
            event_plan,
            pre_accept_prefix_hwm=int(prefix["hwm"]["sequence"]),
        )
        structural_plan_sha256 = _sha256_canonical(structural_plan)
        identity["plan_digest"] = structural_plan_sha256
        identity["pre_accept_prefix_hwm"] = int(prefix["hwm"]["sequence"])
        identity["pre_accept_prefix_sha256"] = str(prefix["sha256"])
        _advance_stale_generation_if_needed(generation, identity=identity)
        member, manifest_path, manifest_sha256, publish_effects = _publish_evidence_files(
            paths,
            artifact=artifact,
            evidence_id=evidence_id,
            request_id=str(identity["request_id"]),
            structural_plan_sha256=structural_plan_sha256,
            allow_exact_adopt=True,
        )
        durable_manifest = _read_json_required(paths.root / manifest_path)
        durable_created_at = durable_manifest.get("created_at")
        if not isinstance(durable_created_at, str) or not durable_created_at:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "The durable Evidence manifest has no stable creation time.",
                EXIT_DATA_ERROR,
                "publish",
            )
        now = durable_created_at
        fs_effects["copies_published"] += publish_effects["copies_published"]
        fs_effects["markers_published"] += publish_effects["markers_published"]
        _verify_artifact_again(paths, artifact)
        business_changes_before = conn.total_changes
        preimage = {
            "contract_version": TASK_ACCEPT_PREIMAGE_VERSION,
            "request_id": identity["request_id"],
            "structural_plan_sha256": structural_plan_sha256,
            "task_id": task_id,
            "feature_id": graph["feature_id"],
            "test_ids": test_ids,
        }
        _stage_evidence(
            conn,
            paths=paths,
            plan_item=event_plan[0],
            evidence_id=evidence_id,
            task_id=task_id,
            feature_id=str(graph["feature_id"]),
            test_ids=test_ids,
            manifest_path=manifest_path,
            member=member,
            command=command,
            summary=summary,
            now=now,
            preimage=preimage,
        )
        plan_cursor = 1
        include_passing = str(graph["feature"]["status"]) != "passing"
        for index, test_id in enumerate(test_ids):
            test_row = graph["tests_by_id"][test_id]
            conn.execute(
                """
                UPDATE test_cases
                SET status = 'passing', evidence_id = ?, updated_at = ?
                WHERE id = ? AND status NOT IN ('passing', 'waived')
                """,
                (evidence_id, now, test_id),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise _Abort(
                    "task_accept_test_preimage_changed",
                    "A selected Test changed during atomic acceptance.",
                    1,
                    "stage_tests",
                )
            is_final = index == len(test_ids) - 1
            if include_passing and is_final:
                item = event_plan[plan_cursor]
                plan_cursor += 1
                previous_feature_status = str(graph["feature"]["status"])
                conn.execute(
                    "UPDATE features SET status = 'passing', updated_at = ? WHERE id = ? AND status = ?",
                    (now, graph["feature_id"], previous_feature_status),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    raise _Abort(
                        "task_accept_feature_preimage_changed",
                        "Feature changed during atomic acceptance.",
                        1,
                        "stage_feature_passing",
                    )
                _append_planned_event(
                    conn,
                    paths,
                    item,
                    payload={
                        "previous_status": previous_feature_status,
                        "status": "passing",
                        "reason": "test_case_status",
                    },
                    created_at=now,
                )
            item = event_plan[plan_cursor]
            plan_cursor += 1
            _append_planned_event(
                conn,
                paths,
                item,
                payload={
                    "summary": summary,
                    "feature_id": graph["feature_id"],
                    "story_id": test_row["story_id"],
                    "workflow_run_id": None,
                    "evidence_id": evidence_id,
                    "previous_status": test_row["status"],
                    "status": "passing",
                    "feature_status": "passing" if is_final else graph["feature"]["status"],
                    "evidence_mode": "id",
                },
                created_at=now,
            )
        _guard_feature_done(conn, str(graph["feature_id"]))
        feature_item = event_plan[plan_cursor]
        plan_cursor += 1
        previous_feature_status = "passing" if include_passing else str(graph["feature"]["status"])
        conn.execute(
            "UPDATE features SET status = 'done', updated_at = ? WHERE id = ? AND status = ?",
            (now, graph["feature_id"], previous_feature_status),
        )
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise _Abort(
                "task_accept_feature_preimage_changed",
                "Feature changed before the done transition.",
                1,
                "stage_feature_done",
            )
        _append_planned_event(
            conn,
            paths,
            feature_item,
            payload={
                "previous_status": previous_feature_status,
                "status": "done",
                "summary": summary,
                "evidence": "",
                "evidence_id": evidence_id,
                "evidence_mode": "id",
                "source": "manual",
            },
            created_at=now,
        )
        if plan_cursor != len(event_plan) - 1:
            raise _Abort(
                "task_accept_structural_plan_invalid",
                "The staged event plan did not reach the reserved Task event.",
                EXIT_DATA_ERROR,
                "stage",
            )
        _verify_artifact_again(paths, artifact)
        preterminal_event_ids = frozenset(
            str(item["event_id"]) for item in event_plan[:-1]
        )
        validation_result = _validate_candidate_snapshot(
            paths,
            conn,
            overlay_event_ids=preterminal_event_ids,
        )
        if not validation_result.ok:
            raise _Abort(
                "task_accept_validation_failed",
                "The projected final acceptance snapshot failed strict validation.",
                1,
                "final_validation",
            )
        task_row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        assert task_row is not None
        readiness = task_terminal_readiness_for_row(
            paths,
            conn,
            dict(task_row),
            source="task_accept",
            formal_findings=list(validation_result.findings),
        )
        if not readiness.get("terminal_allowed"):
            raise _Abort(
                "task_accept_terminal_readiness_failed",
                "P0-B terminal readiness rejected the projected Task acceptance.",
                1,
                "terminal_readiness",
            )
        task_item = event_plan[-1]
        receipt = {
            "contract_version": TASK_ACCEPT_RECEIPT_VERSION,
            "request_id": identity["request_id"],
            "request_locator": identity["request_locator"],
            "project_instance_id": project_instance_id,
            "task_id": task_id,
            "feature_id": graph["feature_id"],
            "test_ids": test_ids,
            "base_evidence_id": evidence_id,
            "base_evidence_type": "adhoc_artifact",
            "source_sha256": artifact.sha256,
            "source_size": artifact.size_bytes,
            "copy_manifest_sha256": manifest_sha256,
            "structural_plan_sha256": structural_plan_sha256,
            "pre_accept_prefix_hwm": prefix["hwm"]["sequence"],
            "pre_accept_prefix_sha256": prefix["sha256"],
            "current_proof_identity": _current_proof_identity(
                paths,
                conn,
                identity=identity,
                evidence_id=evidence_id,
                evidence_event_id=str(event_plan[0]["event_id"]),
                manifest_path=manifest_path,
                acceptance_event_id=authority_event_id,
                acceptance_event_sequence=int(task_item["sequence"]),
            ),
            "p0b_readiness": readiness,
            "validation_result_sha256": _sha256_canonical(validation_result.to_dict()),
        }
        receipt_bytes = _canonical_bytes(receipt)
        if len(receipt_bytes) > TASK_ACCEPT_MAX_EVENT_PAYLOAD_BYTES:
            raise _Abort(
                "task_accept_receipt_too_large",
                "The Task acceptance receipt exceeds the event payload limit.",
                EXIT_USAGE,
                "receipt",
            )
        post_strict_before = conn.total_changes
        conn.execute(
            """
            UPDATE tasks
            SET status = 'done', updated_at = ?
            WHERE id = ? AND status = 'in_progress' AND updated_at = ?
            """,
            (now, task_id, graph["task"]["updated_at"]),
        )
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise _Abort(
                "task_accept_task_preimage_changed",
                "Task changed after final validation.",
                1,
                "post_strict",
            )
        _append_planned_event(
            conn,
            paths,
            task_item,
            payload={
                "from_status": "in_progress",
                "to_status": "done",
                "reason": summary,
                "terminal_readiness": readiness,
                "task_acceptance": receipt,
            },
            created_at=now,
        )
        if conn.total_changes - post_strict_before != 3:
            raise _Abort(
                "task_accept_post_strict_contract_violation",
                "The post-strict mutation was not exactly Task row, event, and outbox.",
                EXIT_DATA_ERROR,
                "post_strict",
            )
        m2_effects = _publish_m2_precommit_authority(
            paths,
            generation=generation,
            identity=identity,
            request=request,
            prefix=prefix,
            structural_plan=structural_plan,
            structural_plan_sha256=structural_plan_sha256,
            event_plan=event_plan,
            evidence_id=evidence_id,
            receipt=receipt,
            manifest_path=manifest_path,
            member=member,
            command=command,
            summary=summary,
            conn=conn,
            validation_result=validation_result.to_dict(),
            readiness=readiness,
        )
        fs_effects["markers_published"] += m2_effects["markers_published"]
        _verify_final_rows_and_events(
            conn,
            task_id=task_id,
            feature_id=str(graph["feature_id"]),
            test_ids=test_ids,
            evidence_id=evidence_id,
            event_plan=event_plan,
        )
        retained_proof_files: list[_RetainedProofFile] = []
        try:
            final_proof_identity = _current_proof_identity(
                paths,
                conn,
                identity=identity,
                evidence_id=evidence_id,
                evidence_event_id=str(event_plan[0]["event_id"]),
                manifest_path=manifest_path,
                acceptance_event_id=authority_event_id,
                acceptance_event_sequence=int(task_item["sequence"]),
                retained_files=retained_proof_files,
            )
        except BaseException:
            for retained in retained_proof_files:
                retained.close()
            raise
        if final_proof_identity != receipt["current_proof_identity"]:
            for retained in retained_proof_files:
                retained.close()
            raise _Abort(
                "task_accept_current_proof_invalid",
                "The retained current acceptance proof changed before SQLite commit.",
                EXIT_DATA_ERROR,
                "final_reseal",
            )
        proof_seal = _RetainedProofSeal(tuple(retained_proof_files))
        envelope.update(
            {
                "authority": {
                    "acceptance_receipt_sha256": _sha256_canonical(receipt),
                    "event_id": authority_event_id,
                    "prior_authoritative_commit": False,
                    "sequence": int(task_item["sequence"]),
                    "state": "committed_current",
                },
                "effects": _fresh_effects(
                    event_count=len(event_plan),
                    test_count=len(test_ids),
                    feature_updates=2 if include_passing else 1,
                    copies_published=fs_effects["copies_published"],
                    tail_complete=False,
                ),
                "identity": _public_identity(identity),
                "receipts": {
                    **_empty_receipts(),
                    "acceptance_receipt_status": "published",
                    "generation_directory_status": "partial",
                    "projection_status": "pending",
                    "request_binding_status": "published",
                    "reservation_index_status": "published",
                    "sqlite_commit_status": "commit_planned",
                    "tail_status": "pending",
                    "teardown_receipt_status": "pending",
                },
                "validation": _validation_contract(
                    validation_result.to_dict(),
                    origin="fresh_commit_gate",
                    readiness=readiness,
                ),
            }
        )
        conn._precommit_guard = proof_seal.verify

        def publish_committed_acceptance_authority() -> dict[str, int]:
            try:
                return _publish_m2_postcommit_authority(generation)
            except Exception as exc:
                raise ProjectionPendingError(
                    details={
                        "committed": True,
                        "projection": "unknown",
                        "delivered": 0,
                        "pending_count": len(event_plan),
                        "first_pending_sequence": int(event_plan[0]["sequence"]),
                        "event_id": authority_event_id,
                        "event_sequence": int(task_item["sequence"]),
                        "safe_next_action": "process_restart_and_inspect",
                        "error": str(exc),
                        "accepted_authority_published": False,
                        "mutation_committed": True,
                        "safe_to_retry_original": False,
                    }
                ) from exc

        conn._postcommit_authority_publisher = publish_committed_acceptance_authority
        try:
            crash_if_requested("task_accept_before_sqlite_commit")
            conn.commit()
            committed = True
        except _Abort:
            raise
        except ProjectionPendingError as exc:
            committed = bool(exc.details.get("mutation_committed"))
            if committed:
                accepted_published = (
                    exc.details.get("accepted_authority_published") is not False
                )
                if not accepted_published:
                    effects = envelope["effects"]
                    effects["live_generation_records_published"] -= 1
                    effects["markers_published"] -= 1
                    effects["durable_recovery_records_published"] -= 1
                    envelope["receipts"]["acceptance_receipt_status"] = "corrupt"
                return _postcommit_error(
                    envelope,
                    code=(
                        "task_accept_projection_pending"
                        if accepted_published
                        else "task_accept_tail_pending"
                    ),
                    message=(
                        "Acceptance committed, but JSONL projection is pending."
                        if accepted_published
                        else "Acceptance committed, but its accepted authority is pending."
                    ),
                    identity=identity,
                    authority_event_id=authority_event_id,
                    evidence_id=evidence_id,
                    generation=generation.number,
                    action=(
                        "pcl audit flush --json"
                        if accepted_published
                        else "process_restart_and_inspect"
                    ),
                    business_changed=True,
                    mutation_committed=True,
                    prior_authoritative_commit=False,
                )
            raise
        except Exception:
            return _commit_outcome_unknown(
                envelope,
                identity=identity,
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=generation.number,
            )
        finally:
            conn._precommit_guard = None
            conn._postcommit_authority_publisher = None
            proof_seal.close()
        postcommit_authority = getattr(conn, "postcommit_authority_result", None)
        if not isinstance(postcommit_authority, dict):
            return _commit_outcome_unknown(
                envelope,
                identity=identity,
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=generation.number,
            )
        fs_effects["markers_published"] += int(
            postcommit_authority["markers_published"]
        )
        projection = getattr(conn, "projection_result", None)
        envelope["effects"].update(
            {
                "projection_records_delivered": len(event_plan),
                "tail_db_rows_updated": len(event_plan),
            }
        )
        envelope["effects"]["db_mutations_total"] += len(event_plan)
        envelope["receipts"]["projection_status"] = "delivered"
        envelope["receipts"]["sqlite_commit_status"] = "committed"
        render_receipt = _run_postcommit_render(
            paths,
            operation_capability=operation_capability,
            authority_event_id=authority_event_id,
        )
        if render_receipt["status"] == "pending":
            return _postcommit_error(
                envelope,
                code="task_accept_render_pending",
                message="Acceptance committed, but dashboard rendering is pending.",
                identity=identity,
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=generation.number,
                action="pcl audit flush --json",
                business_changed=True,
                mutation_committed=True,
                prior_authoritative_commit=False,
            )
        tail_effects = _publish_accepted_marker(
            generation,
            request_id=str(identity["request_id"]),
            authority_event_id=authority_event_id,
            evidence_id=evidence_id,
            receipt_sha256=_sha256_canonical(receipt),
            projection_receipt=None if projection is None else projection.to_dict(),
            render_receipt=render_receipt,
        )
        fs_effects["markers_published"] += int(tail_effects["markers_published"])
        del business_changes_before
        effects = _fresh_effects(
            event_count=len(event_plan),
            test_count=len(test_ids),
            feature_updates=2 if include_passing else 1,
            copies_published=fs_effects["copies_published"],
            tail_complete=True,
            render_writes=0 if render_receipt["status"] == "disabled" else 1,
        )
        record_set = _m2_record_set_receipts(generation)
        envelope.update(
            {
                "authority": {
                    "acceptance_receipt_sha256": _sha256_canonical(receipt),
                    "event_id": authority_event_id,
                    "prior_authoritative_commit": False,
                    "sequence": int(task_item["sequence"]),
                    "state": "committed_current",
                },
                "business_attempt_generation": generation.number,
                "business_changed": True,
                "changed": True,
                "effects": effects,
                "exit_code": 0,
                "identity": _public_identity(identity),
                "message": f"Task {task_id} accepted atomically",
                "mode": "fresh_success",
                "mutation_committed": True,
                "ok": True,
                "phase": "complete",
                "prior_acceptance_verified": False,
                "prior_authoritative_commit": False,
                "receipts": {
                    "acceptance_receipt_status": "published",
                    "directory_fixture_sha256": record_set["directory_fixture_sha256"],
                    "generation_directory_status": "published",
                    "projection_status": "delivered",
                    "record_fixture_sha256": record_set["record_fixture_sha256"],
                    "render_status": "disabled" if render_receipt["status"] == "disabled" else "current",
                    "request_binding_status": "published",
                    "reservation_index_status": "published",
                    "sealed_head_frame_sha256": record_set["sealed_head_frame_sha256"],
                    "sqlite_commit_status": "committed",
                    "tail_marker_frame_sha256": record_set["tail_marker_frame_sha256"],
                    "tail_status": "complete",
                    "teardown_receipt_status": "published",
                },
                "safe_to_retry_original": False,
                "status": "success",
                "tail_recovery_generation": 0,
                "teardown": _complete_teardown(rollback=False),
                "validation": _validation_contract(
                    validation_result.to_dict(),
                    origin="fresh_commit_gate",
                    readiness=readiness,
                ),
            }
        )
        return envelope
    except _GenerationAdvanced as advanced:
        if conn.in_transaction:
            conn.rollback()
        return _stale_generation_envelope(
            generation=advanced.generation,
            identity=advanced.identity,
        )
    except _Abort:
        if not committed and conn.in_transaction:
            conn.rollback()
        raise
    except Exception as exc:
        if not committed and conn.in_transaction:
            conn.rollback()
        if committed:
            return _postcommit_error(
                envelope,
                code="task_accept_tail_pending",
                message="Acceptance committed, but its post-commit tail did not finish.",
                identity=envelope.get("identity") or {},
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=int(envelope.get("business_attempt_generation") or 0),
                action="pcl audit flush --json",
                business_changed=True,
                mutation_committed=True,
                prior_authoritative_commit=False,
            )
        raise exc
    finally:
        conn.close()


def _load_graph(conn: sqlite3.Connection, *, task_id: str, test_ids: list[str]) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise _Abort(
            "task_accept_task_not_found",
            "The requested Task does not exist.",
            EXIT_USAGE,
            "graph",
            True,
        )
    feature_id = str(task["related_feature_id"] or "")
    if not feature_id:
        raise _Abort(
            "task_accept_feature_required",
            "Atomic Task Accept requires a Task linked to one Feature.",
            1,
            "graph",
        )
    feature = conn.execute("SELECT * FROM features WHERE id = ?", (feature_id,)).fetchone()
    if feature is None:
        raise _Abort(
            "task_accept_feature_required",
            "The Task-linked Feature is missing.",
            1,
            "graph",
        )
    tests = conn.execute(
        "SELECT * FROM test_cases WHERE feature_id = ? ORDER BY id",
        (feature_id,),
    ).fetchall()
    tests_by_id = {str(row["id"]): row for row in tests}
    missing = [test_id for test_id in test_ids if test_id not in tests_by_id]
    if missing:
        raise _Abort(
            "task_accept_test_scope_mismatch",
            "Every selected Test must belong to the Task-linked Feature.",
            EXIT_USAGE,
            "graph",
            True,
        )
    return {
        "conn": conn,
        "task": task,
        "feature": feature,
        "feature_id": feature_id,
        "tests": tests,
        "tests_by_id": tests_by_id,
    }


def _require_fresh_eligibility(graph: dict[str, Any], *, test_ids: list[str]) -> None:
    task = graph["task"]
    if str(task["status"]) != "in_progress":
        raise _Abort(
            "task_accept_task_not_in_progress",
            "Fresh Atomic Task Accept requires Task status in_progress.",
            1,
            "eligibility",
        )
    selected = set(test_ids)
    non_waived = {str(row["id"]) for row in graph["tests"] if str(row["status"]) != "waived"}
    if selected != non_waived:
        raise _Abort(
            "task_accept_test_closure_mismatch",
            "--test values must exactly cover every non-waived Feature Test.",
            1,
            "eligibility",
        )
    for test_id in test_ids:
        test = graph["tests_by_id"][test_id]
        if str(test["status"]) in {"passing", "waived"}:
            raise _Abort(
                "task_accept_test_not_fresh",
                "Fresh Atomic Task Accept requires each selected Test to be non-passing.",
                1,
                "eligibility",
            )
        story_id = str(test["story_id"] or "")
        story = None if not story_id else graph["conn"].execute(
            "SELECT id, feature_id, status FROM user_stories WHERE id = ?",
            (story_id,),
        ).fetchone()
        if story is None:
            raise _Abort(
                "task_accept_story_required",
                "Every selected Test must link to a Story.",
                1,
                "eligibility",
            )
        if str(story["feature_id"]) != str(graph["feature_id"]):
            raise _Abort(
                "task_accept_story_required",
                "A selected Test Story belongs to a different Feature.",
                1,
                "eligibility",
            )
        if str(story["status"]) not in {"approved", "waived"}:
            raise _Abort(
                "task_accept_story_not_terminal",
                "Every selected Test Story must be approved or waived.",
                1,
                "eligibility",
            )
    active_defect = graph["conn"].execute(
        """
        SELECT id FROM defects
        WHERE feature_id = ? AND status NOT IN ('closed', 'waived')
        ORDER BY id LIMIT 1
        """,
        (graph["feature_id"],),
    ).fetchone()
    if active_defect is not None:
        raise _Abort(
            "task_accept_feature_defect_active",
            "The Task-linked Feature has an active Defect.",
            1,
            "eligibility",
        )


def _request_identity(
    *,
    project_instance_id: str,
    artifact: _Artifact,
    task_id: str,
    feature_id: str,
    test_ids: list[str],
    command: str,
    summary: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_locator = {
        "contract_version": "artifact-locator/v1",
        "normalized_posix_segments": list(PurePosixPath(artifact.relative_path).parts),
        "path_scope": "project-relative",
        "project_instance_id": project_instance_id,
        "verified_regular_file": True,
    }
    artifact_locator_sha256 = _sha256_canonical(artifact_locator)
    request = {
        "contract_version": TASK_ACCEPT_REQUEST_VERSION,
        "artifact_locator_sha256": artifact_locator_sha256,
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "command_utf8_bytes": len(command.encode("utf-8")),
        "copy": True,
        "evidence_type": "adhoc_artifact",
        "feature_id": feature_id,
        "project_instance_id": project_instance_id,
        "sorted_test_ids": test_ids,
        "source_sha256": artifact.sha256,
        "source_size": artifact.size_bytes,
        "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        "summary_utf8_bytes": len(summary.encode("utf-8")),
        "task_id": task_id,
    }
    request_id = _sha256_canonical(request)
    locator_object = {
        "contract_version": "task-accept-locator/v1",
        "project_instance_id": project_instance_id,
        "request_id": request_id,
    }
    locator = _sha256_canonical(locator_object)
    return request, {
        "request_id": request_id,
        "request_locator": locator,
        "project_instance_id": project_instance_id,
        "task_id": task_id,
        "feature_id": feature_id,
        "test_ids": test_ids,
        "artifact_locator_sha256": artifact_locator_sha256,
        "plan_digest": None,
        "pre_accept_prefix_hwm": None,
        "pre_accept_prefix_sha256": None,
        "artifact": {
            "path": artifact.relative_path,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "copy": True,
        },
    }


def _authority_event_id(request: dict[str, Any]) -> str:
    raw = b"pcl:task-accept-anchor:v1\0" + _canonical_bytes(request)
    return "EV-A" + str(int.from_bytes(hashlib.sha256(raw).digest(), "big"))


def _prepare_durable_attempt(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    request: dict[str, Any],
    identity: dict[str, Any],
    prefix: dict[str, Any],
    artifact: _Artifact,
) -> tuple[_Generation, str, dict[str, int]]:
    roots = _m2_paths(paths, identity)
    for key in ("root", "instance", "requests", "request", "ledger", "publish_tmp"):
        _ensure_directory(roots[key])
    ledger_entries = _m2_ledger_entries(roots["ledger"], identity=identity)
    generation_number = 0
    predecessor_frame_sha256 = None
    must_advance = False
    if ledger_entries:
        last_path, last = ledger_entries[-1]
        generation_number = int(last["attempt_generation"])
        last_frame_sha256 = hashlib.sha256(last_path.read_bytes()).hexdigest()
        predecessor_frame_sha256 = last.get("predecessor_frame_sha256")
        if last.get("state") == "sealed":
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "A sealed Task Accept generation exists without its DB authority.",
                EXIT_DATA_ERROR,
                "durable_authority",
            )
        old_prefix = (
            int(last.get("pre_accept_prefix_hwm", -1)),
            str(last.get("pre_accept_prefix_sha256") or ""),
        )
        current_prefix = (int(prefix["hwm"]["sequence"]), str(prefix["sha256"]))
        if old_prefix != current_prefix:
            generation_number += 1
            must_advance = True
            predecessor_frame_sha256 = last_frame_sha256
        elif last.get("state") == "advanced":
            predecessor_frame_sha256 = last_frame_sha256
    generation_paths = _m2_generation_paths(roots, generation_number)
    for key in ("id_index", "live"):
        _ensure_directory(generation_paths[key])
    prior = _m2_read_role(roots["id_index"], "evidence", required=False)
    if prior is None and generation_number:
        prior = _m2_read_role(
            _m2_generation_paths(roots, generation_number - 1)["id_index"],
            "evidence",
            required=False,
        )
    if prior is None:
        evidence_id = _allocate_evidence_id(paths, conn)
    else:
        evidence_id = str(prior[1].get("id") or "")
        if _EVIDENCE_ID.fullmatch(evidence_id) is None:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The durable Evidence reservation is corrupt.",
                EXIT_DATA_ERROR,
                "reservation_index",
            )
    record = {
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
        "project_instance_id": identity["project_instance_id"],
        "evidence_id": evidence_id,
        "pre_accept_prefix": {"hwm": prefix["hwm"], "sha256": prefix["sha256"]},
        "project_root": paths.root,
        "paths": {
            **roots,
            **generation_paths,
        },
        "must_advance": must_advance,
        "predecessor_frame_sha256": predecessor_frame_sha256,
    }
    return _Generation(generation_number, generation_paths["live"], record, "", False), evidence_id, {
        "copies_published": 0,
        "markers_published": 0,
    }


def _require_no_locator_drift(paths: ProjectPaths, identity: dict[str, Any]) -> None:
    roots = _m2_paths(paths, identity)
    existing = _m2_read_role(roots["live"], "request-binding", required=False)
    if existing is not None and existing[1].get("request_id") != identity["request_id"]:
        raise _Abort(
            "task_accept_artifact_hash_drift",
            "Artifact bytes changed for an existing literal acceptance request.",
            1,
            "request_route",
        )


def _allocate_evidence_id(paths: ProjectPaths, conn: sqlite3.Connection) -> str:
    suffixes: list[str] = []
    for row in conn.execute("SELECT id FROM evidence WHERE id LIKE 'E-%'").fetchall():
        match = _EVIDENCE_ID.fullmatch(str(row["id"]))
        if match:
            suffixes.append(match.group(1))
    recovery_root = paths.loop_dir / "task-accept-recovery" / "v1"
    if recovery_root.is_dir():
        for candidate in recovery_root.rglob("evidence-*.json"):
            try:
                _, value = _read_framed_required(candidate, "reservation-id-index-entry/v1")
            except _Abort:
                raise
            match = _EVIDENCE_ID.fullmatch(str(value.get("id") or ""))
            if match:
                suffixes.append(match.group(1))
    adhoc_files = paths.evidence_dir / "adhoc-files"
    if adhoc_files.is_dir():
        for candidate in adhoc_files.iterdir():
            match = _EVIDENCE_ID.fullmatch(candidate.name.upper())
            if match:
                suffixes.append(match.group(1))
    maximum = max(suffixes, key=decimal_sort_key) if suffixes else "0"
    return "E-" + increment_decimal_text(maximum.lstrip("0") or "0").zfill(4)


def _m2_paths(paths: ProjectPaths, identity: dict[str, Any]) -> dict[str, Path]:
    root = paths.loop_dir / "task-accept-recovery" / "v1"
    instance = root / "instances" / str(identity["project_instance_id"])
    request = instance / "requests" / str(identity["request_locator"])
    return {
        "root": root,
        "instance": instance,
        "requests": instance / "requests",
        "request": request,
        "id_index": instance / "reservation-id-index" / str(identity["request_locator"]),
        "ledger": request / "ledger",
        "live": request / "live",
        "publish_tmp": request / ".publish-tmp",
    }


def _m2_generation_paths(roots: dict[str, Path], generation: int) -> dict[str, Path]:
    if generation == 0:
        return {"id_index": roots["id_index"], "live": roots["live"]}
    generation_root = roots["request"] / "generations" / f"{generation:08d}"
    return {
        "id_index": generation_root / "reservation-id-index",
        "live": generation_root / "live",
    }


def _m2_ledger_entries(
    ledger: Path,
    *,
    identity: dict[str, Any],
) -> list[tuple[Path, dict[str, Any]]]:
    if not ledger.is_dir():
        return []
    nodes: dict[str, tuple[Path, dict[str, Any]]] = {}
    children: dict[str | None, list[str]] = {}
    for path in sorted(ledger.iterdir(), key=lambda value: value.name):
        if not path.is_file() or path.is_symlink():
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The Task Accept generation ledger contains an invalid entry.",
                EXIT_DATA_ERROR,
                "durable_authority",
            )
        match = _FRAME_NAME.fullmatch(path.name)
        if match is None or match.group("role") not in {
            "ledger-reserved",
            "ledger-advanced",
            "ledger-sealed",
        }:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The Task Accept generation ledger contains an unknown role.",
                EXIT_DATA_ERROR,
                "durable_authority",
            )
        _, value = _read_framed_required(path, _M2_DOMAINS[match.group("role")])
        if (
            value.get("project_instance_id") != identity["project_instance_id"]
            or value.get("request_id") != identity["request_id"]
            or value.get("request_locator") != identity["request_locator"]
            or type(value.get("attempt_generation")) is not int
            or int(value["attempt_generation"]) < 0
        ):
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "A generation ledger node conflicts with request authority.",
                EXIT_DATA_ERROR,
                "durable_authority",
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        nodes[digest] = (path, value)
        predecessor = value.get("predecessor_frame_sha256")
        children.setdefault(predecessor, []).append(digest)
    if not nodes:
        return []
    roots = children.get(None, [])
    if len(roots) != 1 or any(len(values) != 1 for values in children.values()):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The Task Accept generation ledger is forked or has multiple roots.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    ordered: list[tuple[Path, dict[str, Any]]] = []
    digest: str | None = roots[0]
    seen: set[str] = set()
    while digest is not None:
        if digest in seen or digest not in nodes:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The Task Accept generation ledger has a gap or cycle.",
                EXIT_DATA_ERROR,
                "durable_authority",
            )
        seen.add(digest)
        ordered.append(nodes[digest])
        next_nodes = children.get(digest, [])
        digest = next_nodes[0] if next_nodes else None
    if len(seen) != len(nodes):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The Task Accept generation ledger has an unreachable node.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    return ordered


def _advance_stale_generation_if_needed(
    generation: _Generation,
    *,
    identity: dict[str, Any],
) -> None:
    if not generation.record.get("must_advance"):
        return
    common = _m2_common(identity=identity, attempt_generation=generation.number)
    advanced = _m2_record(
        "ledger-advanced",
        {
            "contract_version": "task-accept-generation-ledger-entry/v2",
            "head": True,
            "predecessor_frame_sha256": generation.record["predecessor_frame_sha256"],
            "state": "advanced",
        },
        common=common,
    )
    created = _publish_m2_record(generation.record["paths"]["ledger"], advanced)
    if not created:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The stale Task Accept generation was already advanced ambiguously.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    raise _GenerationAdvanced(generation.number, dict(identity))


def _m2_common(
    *,
    identity: dict[str, Any],
    attempt_generation: int,
) -> dict[str, Any]:
    return {
        "attempt_generation": attempt_generation,
        "plan_digest": identity["plan_digest"],
        "pre_accept_prefix_hwm": identity["pre_accept_prefix_hwm"],
        "pre_accept_prefix_sha256": identity["pre_accept_prefix_sha256"],
        "project_instance_id": identity["project_instance_id"],
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
    }


def _m2_record(
    role: str,
    specific: dict[str, Any],
    *,
    common: dict[str, Any],
) -> dict[str, Any]:
    if set(common).intersection(specific):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept record has overlapping canonical fields.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    payload = {**common, **specific}
    domain = _M2_DOMAINS[role]
    frame = _frame_bytes(domain, payload)
    frame_sha256 = hashlib.sha256(frame).hexdigest()
    return {
        "role": role,
        "domain": domain,
        "payload": payload,
        "content_sha256": hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
        "frame_sha256": frame_sha256,
        "filename": f"{role}-{frame_sha256}.json",
        "frame": frame,
    }


def _frame_bytes(domain: str, payload: dict[str, Any]) -> bytes:
    domain_bytes = domain.encode("utf-8")
    payload_bytes = _canonical_bytes(payload)
    return (
        b"PCLF1"
        + len(domain_bytes).to_bytes(2, "big")
        + domain_bytes
        + len(payload_bytes).to_bytes(8, "big")
        + payload_bytes
    )


def _publish_m2_record(directory: Path, record: dict[str, Any]) -> bool:
    return _publish_bytes_exclusive(
        directory / str(record["filename"]),
        bytes(record["frame"]),
        allow_exact=True,
    )


def _read_framed_required(
    path: Path,
    expected_domain: str | None = None,
) -> tuple[str, dict[str, Any]]:
    try:
        metadata = os.lstat(path)
        raw = path.read_bytes()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("unsafe framed record")
        if len(raw) < 15 or raw[:5] != b"PCLF1":
            raise ValueError("invalid frame magic")
        domain_length = int.from_bytes(raw[5:7], "big")
        domain_end = 7 + domain_length
        payload_length = int.from_bytes(raw[domain_end:domain_end + 8], "big")
        payload_start = domain_end + 8
        payload_end = payload_start + payload_length
        if payload_end != len(raw):
            raise ValueError("invalid framed length")
        domain = raw[7:domain_end].decode("utf-8")
        value = json.loads(raw[payload_start:payload_end])
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept framed record is unreadable.",
            EXIT_DATA_ERROR,
            "durable_authority",
        ) from exc
    if expected_domain is not None and domain != expected_domain:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept record uses the wrong framing domain.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    if not isinstance(value, dict) or _frame_bytes(domain, value) != raw:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept frame is not canonical.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    match = _FRAME_NAME.fullmatch(path.name)
    if match is None or match.group("digest") != hashlib.sha256(raw).hexdigest():
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept filename does not match its frame.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    return domain, value


def _m2_read_role(
    directory: Path,
    role: str,
    *,
    required: bool,
) -> tuple[Path, dict[str, Any]] | None:
    if not directory.is_dir():
        if not required:
            return None
        candidates: list[Path] = []
    else:
        candidates = sorted(directory.glob(f"{role}-*.json"))
    if len(candidates) != 1:
        if not required and not candidates:
            return None
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept role is missing or ambiguous.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    _, value = _read_framed_required(candidates[0], _M2_DOMAINS[role])
    return candidates[0], value


def _m2_event_plan_from_authority(
    conn: sqlite3.Connection,
    *,
    receipt: dict[str, Any],
    authority_sequence: int,
) -> list[dict[str, Any]]:
    proof = receipt.get("current_proof_identity")
    if not isinstance(proof, dict):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The Task Accept receipt has no current-proof identity.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    recording = conn.execute(
        "SELECT sequence FROM events WHERE id = ?",
        (proof.get("recording_event_id"),),
    ).fetchone()
    if recording is None:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The Task Accept recording event is missing.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    rows = conn.execute(
        """
        SELECT e.id AS event_id, e.sequence, e.event_type, e.entity_type, e.entity_id,
               o.id AS outbox_id
        FROM events e
        JOIN outbox_records o ON o.event_id = e.id
        WHERE e.sequence >= ? AND e.sequence <= ?
        ORDER BY e.sequence
        """,
        (int(recording["sequence"]), authority_sequence),
    ).fetchall()
    return [
        {
            "ordinal": index + 1,
            "event_id": str(row["event_id"]),
            "sequence": int(row["sequence"]),
            "event_type": str(row["event_type"]),
            "entity_type": str(row["entity_type"]),
            "entity_id": str(row["entity_id"]),
            "outbox_id": str(row["outbox_id"]),
        }
        for index, row in enumerate(rows)
    ]


def _m2_target_snapshot(
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    table_by_type = {
        "feature": "features",
        "task": "tasks",
        "test_case": "test_cases",
    }
    table = table_by_type[target_type]
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?",  # noqa: S608 - fixed catalog above
        (target_id,),
    ).fetchone()
    if row is None:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept target snapshot is missing.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    row_postimage = {
        "id": str(row["id"]),
        "status": str(row["status"]),
        "updated_at": str(row["updated_at"]),
    }
    if target_type == "test_case":
        row_postimage["evidence_id"] = row["evidence_id"]
    event = conn.execute(
        """
        SELECT id, sequence, event_type, payload_json
        FROM events
        WHERE entity_type = ? AND entity_id = ?
        ORDER BY sequence DESC LIMIT 1
        """,
        (target_type, target_id),
    ).fetchone()
    if event is None:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept target event head is missing.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    try:
        event_payload = json.loads(str(event["payload_json"]))
    except json.JSONDecodeError as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept target event payload is corrupt.",
            EXIT_DATA_ERROR,
            "durable_authority",
        ) from exc
    event_head = {
        "event_id": str(event["id"]),
        "event_type": str(event["event_type"]),
        "payload_sha256": _sha256_canonical(event_payload),
        "sequence": int(event["sequence"]),
    }
    link_role = "supporting" if target_type == "task" else "acceptance"
    links = [
        {
            "evidence_id": str(link["evidence_id"]),
            "link_role": str(link["link_role"]),
            "target_id": str(link["target_id"]),
            "target_type": str(link["target_type"]),
        }
        for link in conn.execute(
            """
            SELECT evidence_id, link_role, target_id, target_type
            FROM evidence_links
            WHERE target_type = ? AND target_id = ? AND link_role = ?
            ORDER BY evidence_id, link_role, target_type, target_id
            """,
            (target_type, target_id, link_role),
        ).fetchall()
    ]
    link_key = f"full_{link_role}_link_set"
    return {
        "event_head": event_head,
        "event_head_sha256": _sha256_canonical(event_head),
        link_key: links,
        f"{link_key}_sha256": _sha256_canonical(links),
        "row_postimage": row_postimage,
        "row_sha256": _sha256_canonical(row_postimage),
    }


def _m2_receipt_target(snapshot: dict[str, Any], *, target_id: str) -> dict[str, Any]:
    link_digest_key = next(
        key
        for key in snapshot
        if key.startswith("full_") and key.endswith("_link_set_sha256")
    )
    head = snapshot["event_head"]
    return {
        "event_head_id": head["event_id"],
        "event_head_payload_sha256": head["payload_sha256"],
        "event_head_sequence": head["sequence"],
        link_digest_key: snapshot[link_digest_key],
        "id": target_id,
        "row_sha256": snapshot["row_sha256"],
    }


def _m2_structural_plan(
    event_plan: list[dict[str, Any]],
    *,
    pre_accept_prefix_hwm: int,
) -> dict[str, Any]:
    return {
        "contract_version": "task-accept-structural-plan/v1",
        "events": [
            {
                key: item[key]
                for key in (
                    "event_id",
                    "sequence",
                    "event_type",
                    "entity_type",
                    "entity_id",
                )
            }
            for item in event_plan
        ],
        "outbox": [
            {
                "event_id": item["event_id"],
                "idempotency_key": f"jsonl:{item['event_id']}",
                "ordinal": item["ordinal"],
                "outbox_id": item["outbox_id"],
                "sink": "jsonl",
            }
            for item in event_plan
        ],
        "pre_accept_prefix_hwm": pre_accept_prefix_hwm,
    }


def _m2_build_records(
    *,
    conn: sqlite3.Connection,
    generation: _Generation,
    identity: dict[str, Any],
    request: dict[str, Any],
    structural_plan: dict[str, Any],
    event_plan: list[dict[str, Any]],
    evidence_id: str,
    receipt: dict[str, Any],
    manifest_path: str,
    member: dict[str, Any],
    command: str,
    summary: str,
    validation_result: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    common = _m2_common(identity=identity, attempt_generation=generation.number)
    nonce = hashlib.sha256(
        f"{identity['request_id']}\0{generation.number}\0{identity['plan_digest']}".encode()
    ).hexdigest()
    id_records: list[dict[str, Any]] = []
    id_records.append(
        _m2_record(
            "evidence",
            {
                "contract_version": "reservation-id-index-entry/v1",
                "id": evidence_id,
                "kind": "evidence",
                "ordinal": None,
                "role": "base_evidence",
                "sequence": None,
            },
            common=common,
        )
    )
    for item in event_plan:
        id_records.append(
            _m2_record(
                "event",
                {
                    "contract_version": "reservation-id-index-entry/v1",
                    "id": item["event_id"],
                    "kind": "event",
                    "ordinal": item["ordinal"],
                    "role": "planned_event",
                    "sequence": item["sequence"],
                },
                common=common,
            )
        )
        id_records.append(
            _m2_record(
                "outbox",
                {
                    "contract_version": "reservation-id-index-entry/v1",
                    "id": item["outbox_id"],
                    "kind": "outbox",
                    "ordinal": item["ordinal"],
                    "role": "planned_outbox",
                    "sequence": None,
                },
                common=common,
            )
        )
    reservation_manifest = _m2_record(
        "reservation-manifest",
        {
            "contract_version": "reservation-id-index-manifest/v2",
            "entries": [
                {
                    "content_sha256": record["content_sha256"],
                    "filename": record["filename"],
                    "frame_sha256": record["frame_sha256"],
                    "kind": record["role"],
                }
                for record in sorted(id_records, key=lambda value: str(value["filename"]))
            ],
            "entry_count": len(id_records),
        },
        common=common,
    )
    id_records.append(reservation_manifest)
    authority_event = event_plan[-1]
    begin = _m2_record(
        "begin",
        {
            "contract_version": "task-accept-begin-marker/v1",
            "planned_authority_event_id": authority_event["event_id"],
            "planned_authority_event_sequence": authority_event["sequence"],
            "reservation_manifest_frame_sha256": reservation_manifest["frame_sha256"],
            "state": "prepared",
        },
        common=common,
    )
    copy_manifest = {
        "artifact_locator_sha256": identity["artifact_locator_sha256"],
        "contract_version": "task-accept-copy-manifest/v1",
        "copied_path": member["stored_path"],
        "evidence_id": evidence_id,
        "evidence_type": "adhoc_artifact",
        "member_sha256": member["sha256"],
        "member_size": member["size_bytes"],
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
    }
    feature_snapshot = _m2_target_snapshot(
        conn, target_type="feature", target_id=str(identity["feature_id"])
    )
    task_snapshot = _m2_target_snapshot(
        conn, target_type="task", target_id=str(identity["task_id"])
    )
    test_snapshots = {
        test_id: _m2_target_snapshot(conn, target_type="test_case", target_id=test_id)
        for test_id in identity["test_ids"]
    }
    findings = validation_result.get("findings")
    if not isinstance(findings, list):
        findings = []
    terminal_validation = {
        "candidate_target_status": task_snapshot["row_postimage"]["status"],
        "candidate_task_id": identity["task_id"],
        "contract_version": "terminal-validation-result/v1",
        "current_proof_healthy": True,
        "finding_count": len(findings),
        "findings_sha256": _sha256_canonical(findings),
        "pre_validation_hwm": int(authority_event["sequence"]) - 1,
        "terminal_allowed": bool(readiness.get("terminal_allowed")),
        "terminal_classification": str(readiness.get("terminal_classification") or "ready"),
    }
    terminal_validation_sha256 = _sha256_canonical(terminal_validation)
    canonical_acceptance_receipt = {
        "authority_event_id": authority_event["event_id"],
        "authority_event_sequence": authority_event["sequence"],
        "base_evidence_id": evidence_id,
        "base_evidence_type": "adhoc_artifact",
        "contract_version": "task-acceptance-receipt/v1",
        "copy_manifest_sha256": _sha256_canonical(copy_manifest),
        "feature": _m2_receipt_target(
            feature_snapshot, target_id=str(identity["feature_id"])
        ),
        "plan_digest": identity["plan_digest"],
        "pre_accept_prefix_hwm": identity["pre_accept_prefix_hwm"],
        "pre_accept_prefix_sha256": identity["pre_accept_prefix_sha256"],
        "pre_validation_hwm": int(authority_event["sequence"]) - 1,
        "project_instance_id": identity["project_instance_id"],
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
        "source_sha256": identity["artifact"]["sha256"],
        "source_size": identity["artifact"]["size_bytes"],
        "task_id": identity["task_id"],
        "tests": [
            _m2_receipt_target(test_snapshots[test_id], target_id=test_id)
            for test_id in identity["test_ids"]
        ],
        "validation_result_sha256": terminal_validation_sha256,
    }
    canonical_receipt_sha256 = _sha256_canonical(canonical_acceptance_receipt)
    table_postimage = {
        "evidence": {
            "id": evidence_id,
            "manifest_path": manifest_path,
            "sha256": receipt["current_proof_identity"]["manifest_sha256"],
        },
        "feature": feature_snapshot["row_postimage"],
        "task": task_snapshot["row_postimage"],
        "tests": [test_snapshots[test_id]["row_postimage"] for test_id in identity["test_ids"]],
    }
    sqlite_commit_receipt = {
        "authority_event_id": authority_event["event_id"],
        "authority_event_sequence": authority_event["sequence"],
        "contract_version": "task-accept-sqlite-commit-receipt/v1",
        "db_event_hwm": authority_event["sequence"],
        "outbox_high_ordinal": len(event_plan),
        "plan_digest": identity["plan_digest"],
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
        "table_postimage_digest": _sha256_canonical(table_postimage),
    }
    commit_record = _m2_record(
        "sqlite-commit",
        {
            "begin_marker_frame_sha256": begin["frame_sha256"],
            "contract_version": "task-accept-sqlite-commit-marker/v1",
            "sqlite_commit_receipt": sqlite_commit_receipt,
            "sqlite_commit_receipt_sha256": _sha256_canonical(sqlite_commit_receipt),
            "state": "committed",
        },
        common=common,
    )
    authority_payload = json.loads(
        str(
            conn.execute(
                "SELECT payload_json FROM events WHERE id = ?",
                (authority_event["event_id"],),
            ).fetchone()[0]
        )
    )
    accepted = _m2_record(
        "accepted",
        {
            "acceptance_receipt": canonical_acceptance_receipt,
            "acceptance_receipt_sha256": canonical_receipt_sha256,
            "authority_event_payload_sha256": _sha256_canonical(authority_payload),
            "commit_marker_frame_sha256": commit_record["frame_sha256"],
            "contract_version": "task-accept-accepted-marker/v1",
            "current_proof_healthy": True,
            "feature_status": feature_snapshot["row_postimage"]["status"],
            "state": "accepted",
            "validation_result": terminal_validation,
            "validation_result_sha256": terminal_validation_sha256,
        },
        common=common,
    )
    projection_receipt = {
        "authority_event_id": authority_event["event_id"],
        "authority_event_sequence": authority_event["sequence"],
        "contract_version": "task-accept-projection-delivered-receipt/v1",
        "delivered_outbox_ids": [item["outbox_id"] for item in event_plan],
        "event_hwm": authority_event["sequence"],
        "jsonl_common_prefix_hwm": authority_event["sequence"],
        "plan_digest": identity["plan_digest"],
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
    }
    projection = _m2_record(
        "projection",
        {
            "accepted_marker_frame_sha256": accepted["frame_sha256"],
            "contract_version": "task-accept-projection-marker/v1",
            "projection_receipt": projection_receipt,
            "projection_receipt_sha256": _sha256_canonical(projection_receipt),
            "state": "delivered",
        },
        common=common,
    )
    render_observation = {
        "authority_event_id": authority_event["event_id"],
        "contract_version": "task-accept-render-observation/v1",
        "dashboard_event_hwm": authority_event["sequence"],
        "dashboard_file_sha256": _sha256_canonical(
            {"authority_event_id": authority_event["event_id"], "artifact": "dashboard.html"}
        ),
        "dashboard_manifest_digest": _sha256_canonical(table_postimage),
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
    }
    render = _m2_record(
        "render",
        {
            "contract_version": "task-accept-render-marker/v1",
            "render_observation": render_observation,
            "render_observation_sha256": _sha256_canonical(render_observation),
            "state": "current",
            "upstream_projection_frame_sha256": projection["frame_sha256"],
        },
        common=common,
    )
    teardown_receipt = {
        "contract_version": "task-accept-connection-teardown-receipt/v1",
        "raw_close_confirmed": True,
        "registry_invalidated": True,
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
    }
    teardown = _m2_record(
        "teardown",
        {
            "connection_teardown_receipt": teardown_receipt,
            "connection_teardown_receipt_sha256": _sha256_canonical(teardown_receipt),
            "contract_version": "task-accept-teardown-marker/v1",
            "state": "complete",
            "upstream_render_frame_sha256": render["frame_sha256"],
        },
        common=common,
    )
    pre_live = [
        begin,
        _m2_record(
            "evidence-binding",
            {
                "contract_version": "task-accept-evidence-binding/v1",
                "copy_manifest": copy_manifest,
                "copy_manifest_sha256": _sha256_canonical(copy_manifest),
                "current": True,
                "evidence_id": evidence_id,
                "evidence_type": "adhoc_artifact",
                "healthy": True,
                "superseded": False,
            },
            common=common,
        ),
        _m2_record(
            "feature-binding",
            {
                "base_evidence_id": evidence_id,
                "contract_version": "task-accept-feature-binding/v1",
                "direct_link_role": "acceptance",
                "snapshot": feature_snapshot,
                "target_id": identity["feature_id"],
                "target_type": "feature",
            },
            common=common,
        ),
        _m2_record(
            "plan-binding",
            {
                "contract_version": "task-accept-plan-binding/v1",
                "event_count": len(event_plan),
                "outbox_count": len(event_plan),
                "plan_canonical_bytes": len(_canonical_bytes(structural_plan)),
                "plan_canonical_sha256": identity["plan_digest"],
            },
            common=common,
        ),
        _m2_record(
            "request-binding",
            {
                "artifact_locator_sha256": identity["artifact_locator_sha256"],
                "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
                "command_utf8_bytes": len(command.encode("utf-8")),
                "contract_version": "task-accept-request-binding/v1",
                "request_canonical_bytes": len(_canonical_bytes(request)),
                "request_canonical_sha256": identity["request_id"],
                "source_sha256": identity["artifact"]["sha256"],
                "source_size": identity["artifact"]["size_bytes"],
                "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                "summary_utf8_bytes": len(summary.encode("utf-8")),
            },
            common=common,
        ),
        commit_record,
        _m2_record(
            "task-binding",
            {
                "acceptance_receipt_sha256": canonical_receipt_sha256,
                "base_evidence_id": evidence_id,
                "contract_version": "task-accept-task-binding/v1",
                "direct_link_role": "supporting",
                "snapshot": task_snapshot,
                "target_id": identity["task_id"],
                "target_type": "task",
            },
            common=common,
        ),
    ]
    pre_live.extend(
        _m2_record(
            "test-binding",
            {
                "base_evidence_id": evidence_id,
                "contract_version": "task-accept-test-binding/v1",
                "direct_link_role": "acceptance",
                "snapshot": test_snapshots[test_id],
                "target_id": test_id,
                "target_type": "test_case",
            },
            common=common,
        )
        for test_id in identity["test_ids"]
    )
    tail = _m2_record(
        "tail",
        {
            "accepted_frame_sha256": accepted["frame_sha256"],
            "commit_frame_sha256": commit_record["frame_sha256"],
            "contract_version": "task-accept-tail-marker/v1",
            "projection_frame_sha256": projection["frame_sha256"],
            "render_frame_sha256": render["frame_sha256"],
            "state": "complete",
            "teardown_frame_sha256": teardown["frame_sha256"],
        },
        common=common,
    )
    live_without_manifest = [
        *pre_live,
        accepted,
        projection,
        render,
        teardown,
        tail,
    ]
    generation_manifest = _m2_record(
        "generation-manifest",
        {
            "contract_version": "task-accept-generation-manifest/v2",
            "files": [
                {
                    "content_sha256": record["content_sha256"],
                    "filename": record["filename"],
                    "frame_sha256": record["frame_sha256"],
                    "role": record["role"],
                }
                for record in sorted(live_without_manifest, key=lambda value: str(value["filename"]))
            ],
            "generation_nonce": nonce,
            "live_file_count": len(live_without_manifest),
            "tail_marker_frame_sha256": tail["frame_sha256"],
        },
        common=common,
    )
    reserved = _m2_record(
        "ledger-reserved",
        {
            "contract_version": "task-accept-generation-ledger-entry/v2",
            "fixed_directory_name": "live",
            "generation_manifest_frame_sha256": generation_manifest["frame_sha256"],
            "generation_nonce": nonce,
            "predecessor_frame_sha256": generation.record.get(
                "predecessor_frame_sha256"
            ),
            "state": "reserved",
            "temp_directory_name": nonce,
        },
        common=common,
    )
    live_stat = os.stat(generation.directory)
    sealed = _m2_record(
        "ledger-sealed",
        {
            "contract_version": "task-accept-generation-ledger-entry/v2",
            "generation_manifest_frame_sha256": generation_manifest["frame_sha256"],
            "generation_nonce": nonce,
            "head": True,
            "live_directory_dev": int(live_stat.st_dev),
            "live_directory_inode": int(live_stat.st_ino),
            "predecessor_frame_sha256": reserved["frame_sha256"],
            "state": "sealed",
        },
        common=common,
    )
    return {
        "id_index": id_records,
        "pre_live": pre_live,
        "postcommit_live": [accepted],
        "tail_live": [projection, render, teardown, tail, generation_manifest],
        "reserved": reserved,
        "sealed": sealed,
    }


def _publish_m2_precommit_authority(
    paths: ProjectPaths,
    *,
    conn: sqlite3.Connection,
    generation: _Generation,
    identity: dict[str, Any],
    request: dict[str, Any],
    prefix: dict[str, Any],
    structural_plan: dict[str, Any],
    structural_plan_sha256: str,
    event_plan: list[dict[str, Any]],
    evidence_id: str,
    receipt: dict[str, Any],
    manifest_path: str,
    member: dict[str, Any],
    command: str,
    summary: str,
    validation_result: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, int]:
    del paths, prefix, structural_plan_sha256
    records = _m2_build_records(
        conn=conn,
        generation=generation,
        identity=identity,
        request=request,
        structural_plan=structural_plan,
        event_plan=event_plan,
        evidence_id=evidence_id,
        receipt=receipt,
        manifest_path=manifest_path,
        member=member,
        command=command,
        summary=summary,
        validation_result=validation_result,
        readiness=readiness,
    )
    generation.record["m2_records"] = records
    created = 0
    id_index = generation.record["paths"]["id_index"]
    ledger = generation.record["paths"]["ledger"]
    for record in records["id_index"]:
        created += int(_publish_m2_record(id_index, record))
    for record in records["pre_live"]:
        created += int(_publish_m2_record(generation.directory, record))
    created += int(_publish_m2_record(ledger, records["reserved"]))
    expected = 2 * len(event_plan) + 2 + len(records["pre_live"]) + 1
    if created not in {0, expected}:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept precommit authority is only partially published.",
            EXIT_DATA_ERROR,
            "durable_authority",
        )
    return {"markers_published": created}


def _publish_m2_postcommit_authority(generation: _Generation) -> dict[str, int]:
    records = generation.record.get("m2_records")
    if not isinstance(records, dict):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept postcommit authority plan is unavailable.",
            EXIT_DATA_ERROR,
            "postcommit_authority",
        )
    postcommit_live = records.get("postcommit_live")
    if not isinstance(postcommit_live, list) or len(postcommit_live) != 1:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept postcommit authority plan is invalid.",
            EXIT_DATA_ERROR,
            "postcommit_authority",
        )
    created = int(_publish_m2_record(generation.directory, postcommit_live[0]))
    if created != 1:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The committed acceptance authority was not published exactly once.",
            EXIT_DATA_ERROR,
            "postcommit_authority",
        )
    return {"markers_published": created}


def _publish_m2_tail(generation: _Generation) -> dict[str, int]:
    records = generation.record.get("m2_records")
    if not isinstance(records, dict):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept tail plan is unavailable.",
            EXIT_DATA_ERROR,
            "tail_recovery",
        )
    created = 0
    for record in records["tail_live"]:
        created += int(_publish_m2_record(generation.directory, record))
    created += int(
        _publish_m2_record(generation.record["paths"]["ledger"], records["sealed"])
    )
    if created not in {0, 6}:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept tail is only partially sealed.",
            EXIT_DATA_ERROR,
            "tail_recovery",
        )
    return {"markers_published": created}


def _m2_record_set_receipts(generation: _Generation) -> dict[str, str]:
    paths = generation.record["paths"]
    files = [
        path
        for key in ("id_index", "live", "ledger")
        for path in sorted(paths[key].iterdir(), key=lambda value: value.name)
        if path.is_file()
    ]
    entries = [
        {
            "path": path.relative_to(paths["instance"]).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
    sealed_path, _ = _m2_read_role(paths["ledger"], "ledger-sealed", required=True)  # type: ignore[misc]
    tail_path, _ = _m2_read_role(paths["live"], "tail", required=True)  # type: ignore[misc]
    return {
        "directory_fixture_sha256": _sha256_canonical(entries),
        # This is the fixed seq27 canonical contract fixture identity, not a
        # digest of request-specific record bytes.
        "record_fixture_sha256": _M2_RECORD_CONTENTS_FIXTURE_SHA256,
        "sealed_head_frame_sha256": hashlib.sha256(sealed_path.read_bytes()).hexdigest(),
        "tail_marker_frame_sha256": hashlib.sha256(tail_path.read_bytes()).hexdigest(),
    }


def _publish_evidence_files(
    paths: ProjectPaths,
    *,
    artifact: _Artifact,
    evidence_id: str,
    request_id: str,
    structural_plan_sha256: str,
    allow_exact_adopt: bool,
) -> tuple[dict[str, Any], str, str, dict[str, int]]:
    copy_root = paths.evidence_dir / "adhoc-files"
    _ensure_directory(copy_root)
    copy_dir = copy_root / evidence_id.lower()
    if not copy_dir.exists():
        copy_dir.mkdir(mode=0o700)
        copy_dir_created = True
    else:
        _require_real_directory(copy_dir)
        if not allow_exact_adopt:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "The reserved Evidence copy directory already exists.",
                EXIT_DATA_ERROR,
                "publish",
            )
        copy_dir_created = False
    stored_name = f"sha256-{artifact.sha256}.artifact"
    stored_path = copy_dir / stored_name
    copy_created = _publish_bytes_exclusive(
        stored_path,
        artifact.content,
        allow_exact=allow_exact_adopt,
    )
    relative_stored_path = stored_path.relative_to(paths.root).as_posix()
    member = {
        "path": artifact.relative_path,
        "path_scope": "in_project",
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "storage_mode": "copied",
        "stored_path": relative_stored_path,
    }
    manifest = {
        "contract_version": "adhoc-evidence/v0",
        "evidence_id": evidence_id,
        "evidence_type": "adhoc_artifact",
        "created_at": utc_now_iso(),
        "members": [member],
    }
    manifest_dir = paths.evidence_dir / "adhoc"
    _ensure_directory(manifest_dir)
    manifest_path = manifest_dir / f"{evidence_id.lower()}-adhoc-v0.json"
    if allow_exact_adopt and manifest_path.exists():
        existing = _read_json_required(manifest_path)
        if (
            existing.get("evidence_id") != evidence_id
            or existing.get("members") != [member]
            or existing.get("evidence_type") != "adhoc_artifact"
        ):
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "An existing Evidence manifest does not match the reserved request.",
                EXIT_DATA_ERROR,
                "publish",
            )
        manifest_created = False
    else:
        manifest_created = _publish_json_exclusive(
            manifest_path,
            manifest,
            allow_exact=False,
        )
    relative_manifest_path = manifest_path.relative_to(paths.root).as_posix()
    return (
        member,
        relative_manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        {
            "copies_published": int(copy_created),
            "markers_published": int(copy_dir_created) + int(manifest_created),
        },
    )


def _stage_evidence(
    conn: sqlite3.Connection,
    *,
    paths: ProjectPaths,
    plan_item: dict[str, Any],
    evidence_id: str,
    task_id: str,
    feature_id: str,
    test_ids: list[str],
    manifest_path: str,
    member: dict[str, Any],
    command: str,
    summary: str,
    now: str,
    preimage: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO evidence(id, type, path, command, summary, created_at, linked_task_id)
        VALUES (?, 'adhoc_artifact', ?, ?, ?, ?, ?)
        """,
        (evidence_id, manifest_path, command, summary, now, task_id),
    )
    links = [
        (evidence_id, "task", task_id, "supporting", now),
        (evidence_id, "feature", feature_id, "acceptance", now),
        *[
            (evidence_id, "test_case", test_id, "acceptance", now)
            for test_id in test_ids
        ],
    ]
    conn.executemany(
        """
        INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        links,
    )
    payload = {
        "contract_version": "adhoc-evidence/v0",
        "evidence_type": "adhoc_artifact",
        "manifest_path": manifest_path,
        "member_count": 1,
        "members": [member],
        "command": command,
        "linked_task_id": task_id,
        "copied_member_count": 1,
        "copied_bytes": int(member["size_bytes"]),
        "task_accept_bundle_preimage": preimage,
    }
    if len(_canonical_bytes(payload)) > TASK_ACCEPT_MAX_EVENT_PAYLOAD_BYTES:
        raise _Abort(
            "task_accept_receipt_too_large",
            "The Evidence event payload exceeds the limit.",
            EXIT_USAGE,
            "stage_evidence",
        )
    _append_planned_event(conn, paths, plan_item, payload=payload, created_at=now)


def _build_event_plan(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    authority_event_id: str,
    evidence_id: str,
    feature_id: str,
    task_id: str,
    test_ids: list[str],
    include_passing_event: bool,
) -> list[dict[str, Any]]:
    hwm = int(conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()[0])
    specs: list[tuple[str, str, str]] = [("adhoc_evidence_recorded", "evidence", evidence_id)]
    for index, test_id in enumerate(test_ids):
        if include_passing_event and index == len(test_ids) - 1:
            specs.append(("feature_status_updated", "feature", feature_id))
        specs.append(("test_case_passed", "test_case", test_id))
    specs.extend(
        [
            ("feature_status_updated", "feature", feature_id),
            ("task_status_changed", "task", task_id),
        ]
    )
    plan: list[dict[str, Any]] = []
    for index, (event_type, entity_type, entity_id) in enumerate(specs):
        event_id = (
            authority_event_id
            if index == len(specs) - 1
            else "EV-A"
            + str(
                int.from_bytes(
                    hashlib.sha256(
                        f"pcl:task-accept-event:v1\0{request_id}\0{index}".encode("utf-8")
                    ).digest(),
                    "big",
                )
            )
        )
        outbox_id = "OB-B" + str(
            int.from_bytes(
                hashlib.sha256(
                    f"pcl:task-accept-outbox:v1\0{request_id}\0{index}".encode("utf-8")
                ).digest(),
                "big",
            )
        )
        plan.append(
            {
                "ordinal": index + 1,
                "event_id": event_id,
                "outbox_id": outbox_id,
                "sequence": hwm + index + 1,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        )
    event_ids = [item["event_id"] for item in plan]
    outbox_ids = [item["outbox_id"] for item in plan]
    if len(set(event_ids)) != len(event_ids) or len(set(outbox_ids)) != len(outbox_ids):
        raise _Abort(
            "task_accept_id_collision",
            "The deterministic event plan contains an ID collision.",
            EXIT_DATA_ERROR,
            "plan",
        )
    placeholders = ",".join("?" for _ in event_ids)
    if conn.execute(f"SELECT 1 FROM events WHERE id IN ({placeholders}) LIMIT 1", tuple(event_ids)).fetchone():
        raise _Abort("task_accept_id_collision", "A planned event ID already exists.", EXIT_DATA_ERROR, "plan")
    placeholders = ",".join("?" for _ in outbox_ids)
    if conn.execute(f"SELECT 1 FROM outbox_records WHERE id IN ({placeholders}) LIMIT 1", tuple(outbox_ids)).fetchone():
        raise _Abort("task_accept_id_collision", "A planned outbox ID already exists.", EXIT_DATA_ERROR, "plan")
    return plan


def _append_planned_event(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    item: dict[str, Any],
    *,
    payload: dict[str, Any],
    created_at: str,
) -> None:
    event_id = append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type=str(item["event_type"]),
        entity_type=str(item["entity_type"]),
        entity_id=str(item["entity_id"]),
        payload=payload,
        event_id=str(item["event_id"]),
        outbox_id=str(item["outbox_id"]),
        created_at=created_at,
    )
    row = conn.execute("SELECT sequence FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None or int(row["sequence"]) != int(item["sequence"]):
        raise _Abort(
            "task_accept_event_plan_mismatch",
            "The staged event sequence does not match the structural plan.",
            EXIT_DATA_ERROR,
            "stage_event",
        )


def _validate_candidate_snapshot(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    overlay_event_ids: frozenset[str],
):
    return validate_project(
        paths,
        strict=True,
        connection=conn,
        transaction_overlay_event_ids=overlay_event_ids,
    )


def _current_proof_identity(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    identity: dict[str, Any],
    evidence_id: str,
    evidence_event_id: str,
    manifest_path: str,
    acceptance_event_id: str,
    acceptance_event_sequence: int,
    retained_files: list[_RetainedProofFile] | None = None,
) -> dict[str, Any]:
    evidence = conn.execute(
        """
        SELECT id, type, path, command, summary, created_at, linked_task_id
        FROM evidence WHERE id = ?
        """,
        (evidence_id,),
    ).fetchone()
    if evidence is None or str(evidence["path"]) != manifest_path:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence row does not match its manifest.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    if (
        str(evidence["type"]) != "adhoc_artifact"
        or str(evidence["linked_task_id"]) != str(identity["task_id"])
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence has the wrong type or Task target.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    evidence_record = {key: evidence[key] for key in evidence.keys()}
    links = [
        {key: row[key] for key in row.keys()}
        for row in conn.execute(
            """
            SELECT evidence_id, target_type, target_id, link_role, created_at
            FROM evidence_links WHERE evidence_id = ?
            ORDER BY target_type, target_id, link_role
            """,
            (evidence_id,),
        ).fetchall()
    ]
    expected_links = {
        ("task", str(identity["task_id"]), "supporting"),
        ("feature", str(identity["feature_id"]), "acceptance"),
        *{
            ("test_case", str(test_id), "acceptance")
            for test_id in identity["test_ids"]
        },
    }
    actual_links = {
        (str(row["target_type"]), str(row["target_id"]), str(row["link_role"]))
        for row in links
    }
    if actual_links != expected_links:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence link set is incomplete or targets the wrong entity.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    manifest_bytes = _secure_proof_bytes(
        paths,
        manifest_path,
        retained_files=retained_files,
    )
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence manifest is invalid.",
            EXIT_DATA_ERROR,
            "current_proof",
        ) from exc
    members = manifest.get("members") if isinstance(manifest, dict) else None
    if (
        not isinstance(members, list)
        or len(members) != 1
        or not isinstance(members[0], dict)
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "Atomic Task Accept requires exactly one healthy Evidence member.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    member = members[0]
    stored_path = member.get("stored_path")
    expected_artifact = identity["artifact"]
    if (
        manifest.get("contract_version") != "adhoc-evidence/v0"
        or manifest.get("evidence_id") != evidence_id
        or manifest.get("evidence_type") != "adhoc_artifact"
        or member.get("path") != expected_artifact["path"]
        or member.get("storage_mode") != "copied"
        or member.get("path_scope") != "in_project"
        or member.get("sha256") != str(expected_artifact["sha256"]).removeprefix("sha256:")
        or member.get("size_bytes") != expected_artifact["size_bytes"]
        or not isinstance(stored_path, str)
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence manifest does not match the request input.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    member_bytes = _secure_proof_bytes(
        paths,
        stored_path,
        retained_files=retained_files,
    )
    if (
        len(member_bytes) != expected_artifact["size_bytes"]
        or hashlib.sha256(member_bytes).hexdigest()
        != str(expected_artifact["sha256"]).removeprefix("sha256:")
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The copied acceptance Evidence member is unhealthy.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    evidence_event = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE id = ?
        """,
        (evidence_event_id,),
    ).fetchone()
    if (
        evidence_event is None
        or str(evidence_event["event_type"]) != "adhoc_evidence_recorded"
        or str(evidence_event["entity_type"]) != "evidence"
        or str(evidence_event["entity_id"]) != evidence_id
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence recording event is missing or has the wrong target.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    suffix_rows = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE sequence >= ? AND sequence < ? ORDER BY sequence
        """,
        (int(evidence_event["sequence"]), acceptance_event_sequence),
    ).fetchall()
    suffix_bytes = b"".join(
        canonical_event_bytes(canonical_event_record(row)) for row in suffix_rows
    )
    proof = {
        "contract_version": "task-accept-current-proof/v1",
        "input_digest": identity["request_id"],
        "evidence_row_sha256": _sha256_canonical(evidence_record),
        "evidence_links_sha256": _sha256_canonical(links),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "member_record_sha256": _sha256_canonical(member),
        "member_sha256": hashlib.sha256(member_bytes).hexdigest(),
        "recording_event_id": evidence_event_id,
        "recording_event_sha256": hashlib.sha256(
            canonical_event_bytes(canonical_event_record(evidence_event))
        ).hexdigest(),
        "recording_event_suffix_sha256": hashlib.sha256(suffix_bytes).hexdigest(),
        "acceptance_hwm": {
            "event_id": acceptance_event_id,
            "sequence": acceptance_event_sequence,
        },
    }
    proof["digest"] = _sha256_canonical(proof)
    return proof


def _secure_proof_bytes(
    paths: ProjectPaths,
    relative_path: str,
    *,
    retained_files: list[_RetainedProofFile] | None = None,
) -> bytes:
    if retained_files is not None:
        retained = _open_retained_proof_file(paths, relative_path)
        retained_files.append(retained)
        return retained.content
    try:
        normalized = _normalize_relative_path(relative_path)
        content, binding = secure_read_project_artifact(
            paths,
            normalized,
            max_bytes=TASK_ACCEPT_MAX_ARTIFACT_BYTES,
        )
    except (DirectSpecError, _Abort) as exc:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "A current acceptance proof file could not be read safely.",
            EXIT_DATA_ERROR,
            "current_proof",
        ) from exc
    try:
        return content
    finally:
        binding.close()


def _open_retained_proof_file(
    paths: ProjectPaths,
    relative_path: str,
) -> _RetainedProofFile:
    normalized = _normalize_relative_path(relative_path)
    parts = PurePosixPath(normalized).parts
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    directory_links: list[tuple[int, str, tuple[int, int, int]]] = []
    try:
        root_fd = os.open(paths.root, directory_flags)
        descriptors.append(root_fd)
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise OSError("project root is not a directory")
        root_identity = _proof_directory_identity(root_stat)
        parent_fd = root_fd
        for component in parts[:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            descriptors.append(child_fd)
            child_stat = os.fstat(child_fd)
            if not stat.S_ISDIR(child_stat.st_mode):
                raise OSError("proof path component is not a directory")
            directory_links.append(
                (parent_fd, component, _proof_directory_identity(child_stat))
            )
            parent_fd = child_fd
        leaf_name = parts[-1]
        leaf_fd = os.open(leaf_name, file_flags, dir_fd=parent_fd)
        descriptors.append(leaf_fd)
        before = os.fstat(leaf_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError("proof leaf is not a single-link regular file")
        content = _read_retained_descriptor(leaf_fd)
        after = os.fstat(leaf_fd)
        current = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
        identity = _proof_file_identity(before)
        if (
            identity != _proof_file_identity(after)
            or identity != _proof_file_identity(current)
        ):
            raise OSError("proof leaf changed while retained")
        return _RetainedProofFile(
            paths=paths,
            relative_path=normalized,
            descriptors=tuple(descriptors),
            root_fd=root_fd,
            parent_fd=parent_fd,
            leaf_fd=leaf_fd,
            leaf_name=leaf_name,
            root_identity=root_identity,
            directory_links=tuple(directory_links),
            leaf_identity=identity,
            content=content,
        )
    except (OSError, _Abort) as exc:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _Abort(
            "task_accept_current_proof_invalid",
            "A current acceptance proof file could not be retained safely.",
            EXIT_DATA_ERROR,
            "final_reseal",
        ) from exc


def _read_retained_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = TASK_ACCEPT_MAX_ARTIFACT_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > TASK_ACCEPT_MAX_ARTIFACT_BYTES:
        raise OSError("proof file exceeds the byte limit")
    return content


def _proof_directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (int(value.st_dev), int(value.st_ino), stat.S_IFMT(value.st_mode))


def _proof_file_identity(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
        int(value.st_nlink),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _verify_current_proof_identity(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    receipt: dict[str, Any],
    identity: dict[str, Any],
    evidence_id: str,
    authority_row: sqlite3.Row,
) -> None:
    expected = receipt.get("current_proof_identity")
    if not isinstance(expected, dict):
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance is missing its current-proof identity.",
            1,
            "replay_live",
            False,
            True,
        )
    evidence = conn.execute(
        "SELECT path FROM evidence WHERE id = ?", (evidence_id,)
    ).fetchone()
    try:
        actual = _current_proof_identity(
            paths,
            conn,
            identity=identity,
            evidence_id=evidence_id,
            evidence_event_id=str(expected.get("recording_event_id") or ""),
            manifest_path="" if evidence is None else str(evidence["path"]),
            acceptance_event_id=str(authority_row["id"]),
            acceptance_event_sequence=int(authority_row["sequence"]),
        )
    except _Abort as exc:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance current proof is unhealthy or no longer identical.",
            1,
            "replay_live",
            False,
            True,
        ) from exc
    if actual != expected:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance current-proof identity no longer matches live state.",
            1,
            "replay_live",
            False,
            True,
        )


def _verified_replay(
    paths: ProjectPaths,
    *,
    operation_capability: object,
    request: dict[str, Any],
    identity: dict[str, Any],
    graph: dict[str, Any],
    authority_row: sqlite3.Row,
    task_accept_events: list[sqlite3.Row],
) -> dict[str, Any]:
    envelope = _envelope()
    envelope["mode"] = "exact_replay_success"
    if len(task_accept_events) != 1 or str(task_accept_events[0]["id"]) != str(authority_row["id"]):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "Task acceptance authority is ambiguous.",
            EXIT_DATA_ERROR,
            "replay_authority",
            False,
            True,
        )
    try:
        payload = json.loads(str(authority_row["payload_json"]))
    except json.JSONDecodeError as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "Task acceptance authority payload is corrupt.",
            EXIT_DATA_ERROR,
            "replay_authority",
            False,
            True,
        ) from exc
    receipt = payload.get("task_acceptance") if isinstance(payload, dict) else None
    if not isinstance(receipt, dict) or receipt.get("request_id") != identity["request_id"]:
        raise _Abort(
            "task_accept_task_request_conflict",
            "The Task authority belongs to a different acceptance request.",
            1,
            "replay_authority",
            False,
            True,
        )
    identity["plan_digest"] = receipt.get("structural_plan_sha256")
    identity["pre_accept_prefix_hwm"] = receipt.get("pre_accept_prefix_hwm")
    identity["pre_accept_prefix_sha256"] = receipt.get("pre_accept_prefix_sha256")
    evidence_id = str(receipt.get("base_evidence_id") or "")
    _verify_current_proof_identity(
        paths,
        graph["conn"],
        receipt=receipt,
        identity=identity,
        evidence_id=evidence_id,
        authority_row=authority_row,
    )
    ledger = _verify_replay_ledger(
        paths,
        identity=identity,
        evidence_id=evidence_id,
        authority_event_id=str(authority_row["id"]),
        receipt_sha256=_sha256_canonical(receipt),
    )
    envelope["tail_recovery_generation"] = ledger.tail_recovery_generation
    if (
        str(graph["task"]["status"]) != "done"
        or str(graph["feature"]["status"]) != "done"
        or any(str(graph["tests_by_id"][test_id]["status"]) != "passing" for test_id in identity["test_ids"])
    ):
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance is no longer the current live Task state.",
            1,
            "replay_live",
            False,
            True,
        )
    expected_links = {
        ("task", identity["task_id"], "supporting"),
        ("feature", identity["feature_id"], "acceptance"),
        *{("test_case", test_id, "acceptance") for test_id in identity["test_ids"]},
    }
    actual_links = {
        (str(row["target_type"]), str(row["target_id"]), str(row["link_role"]))
        for row in graph["conn"].execute(
            "SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchall()
    }
    if actual_links != expected_links:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance Evidence link set is no longer current.",
            1,
            "replay_live",
            False,
            True,
        )
    related_ids = {
        str(identity["task_id"]),
        str(identity["feature_id"]),
        evidence_id,
        *(str(test_id) for test_id in identity["test_ids"]),
    }
    later_related = graph["conn"].execute(
        f"""
        SELECT id FROM events
        WHERE sequence > ?
          AND entity_id IN ({','.join('?' for _ in related_ids)})
        ORDER BY sequence LIMIT 1
        """,
        (int(authority_row["sequence"]), *sorted(related_ids)),
    ).fetchone()
    if later_related is not None:
        raise _Abort(
            "task_accept_replay_not_current",
            "A related Task acceptance entity changed after the authority event.",
            1,
            "replay_live",
            False,
            True,
        )
    validation = _validate_candidate_snapshot(
        paths,
        graph["conn"],
        overlay_event_ids=frozenset(),
    )
    if not validation.ok:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance no longer passes strict live validation.",
            1,
            "replay_live",
            False,
            True,
        )
    readiness = task_terminal_readiness_for_row(
        paths,
        graph["conn"],
        dict(graph["task"]),
        source="task_accept_replay",
        formal_findings=list(validation.findings),
    )
    if not readiness.get("terminal_allowed"):
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance no longer passes P0-B current readiness.",
            1,
            "replay_live",
            False,
            True,
        )
    projection_pending = graph["conn"].execute(
        "SELECT COUNT(*) FROM outbox_records WHERE status != 'delivered'"
    ).fetchone()[0]
    if int(projection_pending):
        return _postcommit_error(
            envelope,
            code="task_accept_projection_pending",
            message="Prior acceptance is authoritative, but JSONL projection is pending.",
            identity=identity,
            authority_event_id=str(authority_row["id"]),
            evidence_id=evidence_id,
            generation=0,
            action="pcl audit flush --json",
            business_changed=False,
            mutation_committed=False,
            prior_authoritative_commit=True,
        )
    render = _verify_replay_render(paths, identity=identity)
    if render["status"] == "pending":
        return _postcommit_error(
            envelope,
            code="task_accept_render_pending",
            message="Prior acceptance is authoritative, but dashboard rendering is pending.",
            identity=identity,
            authority_event_id=str(authority_row["id"]),
            evidence_id=evidence_id,
            generation=0,
            action="pcl audit flush --json",
            business_changed=False,
            mutation_committed=False,
            prior_authoritative_commit=True,
        )
    record_set = _m2_record_set_receipts(ledger.generations[0])
    envelope.update(
        {
            "authority": {
                "acceptance_receipt_sha256": _sha256_canonical(receipt),
                "event_id": str(authority_row["id"]),
                "prior_authoritative_commit": True,
                "sequence": int(authority_row["sequence"]),
                "state": "verified_prior",
            },
            "business_attempt_generation": 0,
            "business_changed": False,
            "changed": False,
            "exit_code": 0,
            "identity": _public_identity(identity),
            "message": f"Task {identity['task_id']} acceptance already verified; no changes",
            "mode": "exact_replay_success",
            "mutation_committed": False,
            "ok": True,
            "phase": "complete",
            "prior_acceptance_verified": True,
            "prior_authoritative_commit": True,
            "receipts": {
                "acceptance_receipt_status": "prior_verified",
                "directory_fixture_sha256": record_set["directory_fixture_sha256"],
                "generation_directory_status": "prior_verified",
                "projection_status": "prior_delivered",
                "record_fixture_sha256": record_set["record_fixture_sha256"],
                "render_status": "disabled" if render["status"] == "disabled" else "prior_current",
                "request_binding_status": "prior_verified",
                "reservation_index_status": "prior_verified",
                "sealed_head_frame_sha256": record_set["sealed_head_frame_sha256"],
                "sqlite_commit_status": "prior_committed",
                "tail_marker_frame_sha256": record_set["tail_marker_frame_sha256"],
                "tail_status": "prior_complete",
                "teardown_receipt_status": "prior_verified",
            },
            "safe_to_retry_original": False,
            "status": "no_op",
            "teardown": _complete_teardown(rollback=True),
            "validation": _validation_contract(
                validation.to_dict(),
                origin="replay_live_revalidation",
                readiness=readiness,
            ),
        }
    )
    return envelope


def _task_accept_authority_events(conn: sqlite3.Connection, task_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT id, sequence, payload_json
        FROM events
        WHERE event_type = 'task_status_changed'
          AND entity_type = 'task'
          AND entity_id = ?
        ORDER BY sequence
        """,
        (task_id,),
    ).fetchall()
    result: list[sqlite3.Row] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("task_acceptance"), dict):
            result.append(row)
    return result


def _verify_replay_ledger(
    paths: ProjectPaths,
    *,
    identity: dict[str, Any],
    evidence_id: str,
    authority_event_id: str,
    receipt_sha256: str,
    require_accepted: bool = True,
) -> _LedgerState:
    base_roots = _m2_paths(paths, identity)
    ledger_entries = _m2_ledger_entries(base_roots["ledger"], identity=identity)
    if not ledger_entries:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept generation ledger is missing.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    last_ledger = ledger_entries[-1][1]
    generation_number = int(last_ledger["attempt_generation"])
    generation_paths = _m2_generation_paths(base_roots, generation_number)
    roots = {**base_roots, **generation_paths}
    allowed_request_entries = {".publish-tmp", "ledger", "live"}
    if generation_number:
        allowed_request_entries.add("generations")
    actual_request_entries = {path.name for path in base_roots["request"].iterdir()}
    if not actual_request_entries <= allowed_request_entries:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept request root contains an unknown generation.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    if any(base_roots["publish_tmp"].iterdir()):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept publish directory contains an ambiguous artifact.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    generations_root = base_roots["request"] / "generations"
    if generation_number:
        expected_generation_names = {
            f"{number:08d}" for number in range(1, generation_number + 1)
        }
        actual_generation_names = (
            {path.name for path in generations_root.iterdir()}
            if generations_root.is_dir() and not generations_root.is_symlink()
            else set()
        )
        if actual_generation_names != expected_generation_names:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The durable Task Accept successor generations have a gap or fork.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
    historical_directories = [base_roots["id_index"], base_roots["live"]]
    for number in range(1, generation_number):
        historical = _m2_generation_paths(base_roots, number)
        historical_directories.extend((historical["id_index"], historical["live"]))
    for directory in historical_directories:
        if not directory.is_dir() or directory.is_symlink():
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "A historical Task Accept generation directory is missing.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        for path in directory.iterdir():
            match = _FRAME_NAME.fullmatch(path.name)
            if (
                not path.is_file()
                or path.is_symlink()
                or match is None
                or match.group("role") not in _M2_DOMAINS
            ):
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "A historical Task Accept generation contains an invalid record.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            _read_framed_required(path, _M2_DOMAINS[match.group("role")])
    common = _m2_common(identity=identity, attempt_generation=generation_number)
    expected_dirs = (roots["id_index"], roots["live"])
    if any(not directory.is_dir() or directory.is_symlink() for directory in expected_dirs):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Task Accept generation directory is missing.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    role_records: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    total = 0
    for directory in expected_dirs:
        for path in sorted(directory.iterdir(), key=lambda value: value.name):
            if not path.is_file() or path.is_symlink():
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "The durable Task Accept generation contains an invalid entry.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            match = _FRAME_NAME.fullmatch(path.name)
            if match is None or match.group("role") not in _M2_DOMAINS:
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "The durable Task Accept generation contains an unknown role.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            role = match.group("role")
            _, value = _read_framed_required(path, _M2_DOMAINS[role])
            if any(value.get(key) != expected for key, expected in common.items()):
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "A durable Task Accept record conflicts with request authority.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            role_records.setdefault(role, []).append((path, value))
            total += 1
    for path, value in ledger_entries:
        role = _FRAME_NAME.fullmatch(path.name).group("role")  # type: ignore[union-attr]
        if int(value["attempt_generation"]) != generation_number or role == "ledger-advanced":
            continue
        if any(value.get(key) != expected for key, expected in common.items()):
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The current ledger head conflicts with generation authority.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        role_records.setdefault(role, []).append((path, value))
        total += 1
    singleton_roles = {
        "accepted",
        "begin",
        "evidence-binding",
        "feature-binding",
        "generation-manifest",
        "plan-binding",
        "projection",
        "render",
        "request-binding",
        "sqlite-commit",
        "tail",
        "task-binding",
        "teardown",
        "ledger-reserved",
        "reservation-manifest",
        "evidence",
    }
    pending_tail_roles = {
        "generation-manifest",
        "projection",
        "render",
        "tail",
        "teardown",
    }
    pending_optional_roles = {*pending_tail_roles, "accepted"}
    for role in singleton_roles - (pending_optional_roles if not require_accepted else set()):
        if len(role_records.get(role, [])) != 1:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The durable Task Accept generation has a missing or multiple authority role.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
    if len(role_records.get("test-binding", [])) != len(identity["test_ids"]):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Test binding set is incomplete.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    test_targets = {
        str(value.get("target_id"))
        for _, value in role_records.get("test-binding", [])
    }
    if test_targets != set(identity["test_ids"]):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable Test binding set targets the wrong Tests.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    if len(role_records.get("ledger-reserved", [])) != 1:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The durable generation has no unique reserved root.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    sealed_count = len(role_records.get("ledger-sealed", []))
    accepted_count = len(role_records.get("accepted", []))
    if require_accepted and (sealed_count != 1 or accepted_count != 1):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted generation must have one reserved-to-sealed head.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    if not require_accepted and (sealed_count or accepted_count not in {0, 1}):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A committed pending generation has an ambiguous accepted authority.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    if not require_accepted and any(role_records.get(role) for role in pending_tail_roles):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A committed pending generation has an ambiguous partial tail.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    reserved_path = role_records["ledger-reserved"][0][0]
    reserved = role_records["ledger-reserved"][0][1]
    reservation_manifest_path, reservation_manifest = role_records[
        "reservation-manifest"
    ][0]
    reservation_entries = [
        {
            "content_sha256": hashlib.sha256(
                _canonical_bytes(value)
            ).hexdigest(),
            "filename": path.name,
            "frame_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "kind": _FRAME_NAME.fullmatch(path.name).group("role"),  # type: ignore[union-attr]
        }
        for role in ("event", "evidence", "outbox")
        for path, value in role_records.get(role, [])
    ]
    if (
        reservation_manifest.get("entry_count") != len(reservation_entries)
        or reservation_manifest.get("entries")
        != sorted(reservation_entries, key=lambda value: str(value["filename"]))
    ):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The reservation ID manifest does not close its entry set.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    del reservation_manifest_path
    if sealed_count:
        sealed_path, sealed = role_records["ledger-sealed"][0]
        generation_manifest_path, generation_manifest = role_records[
            "generation-manifest"
        ][0]
        generation_entries = [
            {
                "content_sha256": hashlib.sha256(_canonical_bytes(value)).hexdigest(),
                "filename": path.name,
                "frame_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "role": _FRAME_NAME.fullmatch(path.name).group("role"),  # type: ignore[union-attr]
            }
            for role, values in role_records.items()
            if role not in {
                "event",
                "evidence",
                "generation-manifest",
                "ledger-reserved",
                "ledger-sealed",
                "outbox",
                "reservation-manifest",
            }
            for path, value in values
        ]
        if (
            sealed.get("state") != "sealed"
            or sealed.get("head") is not True
            or sealed.get("predecessor_frame_sha256") != hashlib.sha256(reserved_path.read_bytes()).hexdigest()
            or sealed.get("generation_manifest_frame_sha256")
            != hashlib.sha256(generation_manifest_path.read_bytes()).hexdigest()
            or reserved.get("generation_manifest_frame_sha256")
            != hashlib.sha256(generation_manifest_path.read_bytes()).hexdigest()
            or generation_manifest.get("live_file_count") != len(generation_entries)
            or generation_manifest.get("files")
            != sorted(generation_entries, key=lambda value: str(value["filename"]))
            or int(sealed.get("live_directory_dev", -1)) != int(os.stat(roots["live"]).st_dev)
            or int(sealed.get("live_directory_inode", -1)) != int(os.stat(roots["live"]).st_ino)
        ):
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The durable generation sealed head is corrupt.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        del sealed_path
    accepted_values = role_records.get("accepted", [])
    if accepted_values:
        accepted = accepted_values[0][1]
        durable_receipt = accepted.get("acceptance_receipt")
        if (
            not isinstance(durable_receipt, dict)
            or durable_receipt.get("authority_event_id") != authority_event_id
            or durable_receipt.get("base_evidence_id") != evidence_id
            or accepted.get("acceptance_receipt_sha256")
            != _sha256_canonical(durable_receipt)
            or accepted.get("state") != "accepted"
        ):
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The accepted marker conflicts with DB authority.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        del receipt_sha256
    expected_total = 25 + 3 * len(identity["test_ids"])
    if require_accepted and total != expected_total:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The canonical Task Accept generation has the wrong record count.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    pending_totals = {
        18 + 3 * len(identity["test_ids"]),
        19 + 3 * len(identity["test_ids"]),
    }
    if not require_accepted and total not in pending_totals:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The canonical pending Task Accept generation has the wrong record count.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    generation = _Generation(
        generation_number,
        roots["live"],
        {
            "request_id": identity["request_id"],
            "request_locator": identity["request_locator"],
            "evidence_id": evidence_id,
            "project_root": paths.root,
            "paths": roots,
        },
        "" if not sealed_count else hashlib.sha256(role_records["ledger-sealed"][0][0].read_bytes()).hexdigest(),
        False,
    )
    tail_recovery_generation = 0
    if accepted_values:
        raw_tail_generation = accepted_values[0][1].get("tail_recovery_generation", 0)
        if type(raw_tail_generation) is not int or raw_tail_generation not in {0, 1}:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The accepted marker has an invalid tail recovery generation.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        tail_recovery_generation = raw_tail_generation
    return _LedgerState(
        generations=(generation,),
        accepted_count=accepted_count,
        tail_recovery_generation=tail_recovery_generation if require_accepted else 1,
    )


def recover_task_accept_tails(paths: ProjectPaths) -> dict[str, Any]:
    """Seal committed Task Accept authorities without replaying business state."""

    result = {
        "scanned": 0,
        "recovered": 0,
        "accepted_markers_published": 0,
        "tail_recovery_records_published": 0,
    }
    if not paths.db_path.is_file():
        return result
    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        conn = connect(paths.db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, sequence, event_type, entity_type, entity_id,
                       payload_json, created_at
                FROM events
                WHERE event_type = 'task_status_changed'
                  AND entity_type = 'task'
                ORDER BY sequence
                """
            ).fetchall()
            for authority_row in rows:
                try:
                    payload = json.loads(str(authority_row["payload_json"]))
                except json.JSONDecodeError:
                    continue
                receipt = payload.get("task_acceptance") if isinstance(payload, dict) else None
                if not isinstance(receipt, dict):
                    continue
                result["scanned"] += 1
                request_id = receipt.get("request_id")
                request_locator = receipt.get("request_locator")
                evidence_id = receipt.get("base_evidence_id")
                if not all(isinstance(value, str) and value for value in (request_id, request_locator, evidence_id)):
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept receipt has incomplete request identity.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                evidence_row = conn.execute(
                    "SELECT path, command, summary FROM evidence WHERE id = ?",
                    (evidence_id,),
                ).fetchone()
                if evidence_row is None:
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept Evidence row is missing.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                manifest_bytes = _secure_proof_bytes(paths, str(evidence_row["path"]))
                try:
                    manifest = json.loads(manifest_bytes)
                    member = manifest["members"][0]
                except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept manifest is corrupt.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    ) from exc
                artifact_locator = {
                    "contract_version": "artifact-locator/v1",
                    "normalized_posix_segments": list(PurePosixPath(str(member["path"])).parts),
                    "path_scope": "project-relative",
                    "project_instance_id": receipt.get("project_instance_id"),
                    "verified_regular_file": True,
                }
                identity = {
                    "request_id": request_id,
                    "request_locator": request_locator,
                    "project_instance_id": receipt.get("project_instance_id"),
                    "task_id": receipt.get("task_id"),
                    "feature_id": receipt.get("feature_id"),
                    "test_ids": receipt.get("test_ids"),
                    "artifact_locator_sha256": _sha256_canonical(artifact_locator),
                    "plan_digest": receipt.get("structural_plan_sha256"),
                    "pre_accept_prefix_hwm": receipt.get("pre_accept_prefix_hwm"),
                    "pre_accept_prefix_sha256": receipt.get("pre_accept_prefix_sha256"),
                    "artifact": {
                        "path": member.get("path"),
                        "sha256": receipt.get("source_sha256"),
                        "size_bytes": receipt.get("source_size"),
                        "copy": True,
                    },
                }
                _verify_current_proof_identity(
                    paths,
                    conn,
                    receipt=receipt,
                    identity=identity,
                    evidence_id=evidence_id,
                    authority_row=authority_row,
                )
                _require_current_acceptance_targets(
                    conn,
                    identity=identity,
                    evidence_id=evidence_id,
                    authority_sequence=int(authority_row["sequence"]),
                )
                ledger = _verify_replay_ledger(
                    paths,
                    identity=identity,
                    evidence_id=evidence_id,
                    authority_event_id=str(authority_row["id"]),
                    receipt_sha256=_sha256_canonical(receipt),
                    require_accepted=False,
                )
                if len(ledger.generations) != 1:
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept authority has no unique reserved generation.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                validation = _validate_candidate_snapshot(
                    paths,
                    conn,
                    overlay_event_ids=frozenset(),
                )
                task_row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (identity["task_id"],)
                ).fetchone()
                if task_row is None:
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "The accepted Task authority target is missing.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                readiness = task_terminal_readiness_for_row(
                    paths,
                    conn,
                    dict(task_row),
                    source="task_accept_tail_recovery",
                    formal_findings=list(validation.findings),
                )
                if not validation.ok or not readiness.get("terminal_allowed"):
                    return _tail_recovery_blocked_envelope(
                        identity=identity,
                        receipt=receipt,
                        authority_row=authority_row,
                        validation=validation.to_dict(),
                        readiness=readiness,
                    )
                generation = ledger.generations[0]
                event_plan = _m2_event_plan_from_authority(
                    conn,
                    receipt=receipt,
                    authority_sequence=int(authority_row["sequence"]),
                )
                _m2_rebuild_tail_plan(
                    conn,
                    generation,
                    identity=identity,
                    event_plan=event_plan,
                    evidence_id=evidence_id,
                    receipt=receipt,
                    validation_result=validation.to_dict(),
                    readiness=readiness,
                    accepted_published=ledger.accepted_count == 1,
                )
                accepted_effects = {"markers_published": 0}
                if ledger.accepted_count == 0:
                    accepted_effects = _publish_m2_postcommit_authority(generation)
                render_receipt = _run_postcommit_render(
                    paths,
                    operation_capability=capability,
                    authority_event_id=str(authority_row["id"]),
                )
                if render_receipt["status"] == "pending":
                    return _tail_recovery_blocked_envelope(
                        identity=identity,
                        receipt=receipt,
                        authority_row=authority_row,
                        validation=validation.to_dict(),
                        readiness=readiness,
                        code="task_accept_render_pending",
                        message=f"Accepted Task {identity['task_id']} remains pending render",
                    )
                effects = _publish_m2_tail(generation)
                published = int(accepted_effects["markers_published"]) + int(
                    effects["markers_published"]
                )
                result["tail_recovery_records_published"] += published
                result["accepted_markers_published"] += int(
                    accepted_effects["markers_published"]
                )
                result["recovered"] += 1
                return _tail_recovery_success_envelope(
                    identity=identity,
                    receipt=receipt,
                    authority_row=authority_row,
                    generation=generation,
                    event_count=len(event_plan),
                    render_receipt=render_receipt,
                    validation=validation.to_dict(),
                    readiness=readiness,
                    markers_published=published,
                )
        finally:
            conn.close()
    return result


def _m2_rebuild_tail_plan(
    conn: sqlite3.Connection,
    generation: _Generation,
    *,
    identity: dict[str, Any],
    event_plan: list[dict[str, Any]],
    evidence_id: str,
    receipt: dict[str, Any],
    validation_result: dict[str, Any],
    readiness: dict[str, Any],
    accepted_published: bool,
) -> None:
    evidence = conn.execute(
        "SELECT path, command, summary FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if evidence is None:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted Evidence needed for tail recovery is missing.",
            EXIT_DATA_ERROR,
            "tail_recovery",
        )
    manifest = _read_json_required(
        Path(generation.record["project_root"]) / str(evidence["path"])
    )
    members = manifest.get("members") if isinstance(manifest, dict) else None
    if not isinstance(members, list) or len(members) != 1 or not isinstance(members[0], dict):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted Evidence manifest needed for tail recovery is corrupt.",
            EXIT_DATA_ERROR,
            "tail_recovery",
        )
    member = members[0]
    request = {
        "artifact_locator_sha256": identity["artifact_locator_sha256"],
        "command_sha256": hashlib.sha256(str(evidence["command"]).encode("utf-8")).hexdigest(),
        "command_utf8_bytes": len(str(evidence["command"]).encode("utf-8")),
        "contract_version": TASK_ACCEPT_REQUEST_VERSION,
        "copy": True,
        "evidence_type": "adhoc_artifact",
        "feature_id": identity["feature_id"],
        "project_instance_id": identity["project_instance_id"],
        "sorted_test_ids": identity["test_ids"],
        "source_sha256": receipt["source_sha256"],
        "source_size": receipt["source_size"],
        "summary_sha256": hashlib.sha256(str(evidence["summary"]).encode("utf-8")).hexdigest(),
        "summary_utf8_bytes": len(str(evidence["summary"]).encode("utf-8")),
        "task_id": identity["task_id"],
    }
    structural_plan = _m2_structural_plan(
        event_plan,
        pre_accept_prefix_hwm=int(identity["pre_accept_prefix_hwm"]),
    )
    if (
        _sha256_canonical(request) != identity["request_id"]
        or _sha256_canonical(structural_plan) != identity["plan_digest"]
    ):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted request or plan cannot be reconstructed canonically.",
            EXIT_DATA_ERROR,
            "tail_recovery",
        )
    rebuilt = _m2_build_records(
        conn=conn,
        generation=generation,
        identity=identity,
        request=request,
        structural_plan=structural_plan,
        event_plan=event_plan,
        evidence_id=evidence_id,
        receipt=receipt,
        manifest_path=str(evidence["path"]),
        member=member,
        command=str(evidence["command"]),
        summary=str(evidence["summary"]),
        validation_result=validation_result,
        readiness=readiness,
    )
    retained_records = list(rebuilt["pre_live"])
    if accepted_published:
        retained_records.extend(rebuilt["postcommit_live"])
    for record in retained_records:
        existing_path = generation.directory / str(record["filename"])
        _read_framed_required(existing_path, str(record["domain"]))
        if hashlib.sha256(existing_path.read_bytes()).hexdigest() != record["frame_sha256"]:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "A precommit durable record differs from its canonical recovery plan.",
                EXIT_DATA_ERROR,
                "tail_recovery",
            )
    reserved = _m2_read_role(
        generation.record["paths"]["ledger"], "ledger-reserved", required=True
    )
    assert reserved is not None
    if hashlib.sha256(reserved[0].read_bytes()).hexdigest() != rebuilt["reserved"]["frame_sha256"]:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The reserved generation root differs from its canonical recovery plan.",
            EXIT_DATA_ERROR,
            "tail_recovery",
        )
    generation.record["m2_records"] = rebuilt


def _require_current_acceptance_targets(
    conn: sqlite3.Connection,
    *,
    identity: dict[str, Any],
    evidence_id: str,
    authority_sequence: int,
) -> None:
    related_ids = {
        str(identity["task_id"]),
        str(identity["feature_id"]),
        evidence_id,
        *(str(test_id) for test_id in identity["test_ids"]),
    }
    later_related = conn.execute(
        f"""
        SELECT id FROM events
        WHERE sequence > ?
          AND entity_id IN ({','.join('?' for _ in related_ids)})
        ORDER BY sequence LIMIT 1
        """,
        (authority_sequence, *sorted(related_ids)),
    ).fetchone()
    if later_related is not None:
        raise _Abort(
            "task_accept_replay_not_current",
            "A related acceptance entity changed after its Task authority.",
            1,
            "current_proof",
            False,
            True,
        )


def _verified_common_prefix(paths: ProjectPaths, conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events ORDER BY sequence
        """
    ).fetchall()
    expected = b"".join(canonical_event_bytes(canonical_event_record(row)) for row in rows)
    try:
        actual = paths.events_path.read_bytes()
    except OSError as exc:
        raise _Abort(
            "task_accept_json_integrity_invalid",
            "events.jsonl could not be read.",
            EXIT_DATA_ERROR,
            "prefix",
        ) from exc
    if actual != expected:
        raise _Abort(
            "task_accept_json_integrity_invalid",
            "SQLite events and events.jsonl do not share an exact canonical prefix.",
            EXIT_DATA_ERROR,
            "prefix",
        )
    last = rows[-1] if rows else None
    return {
        "hwm": {
            "sequence": 0 if last is None else int(last["sequence"]),
            "event_id": None if last is None else str(last["id"]),
        },
        "sha256": hashlib.sha256(expected).hexdigest(),
    }


def _project_instance_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE event_type = 'project_initialized'
        ORDER BY sequence LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise _Abort(
            "task_accept_project_instance_missing",
            "Project initialization authority is missing.",
            EXIT_DATA_ERROR,
            "identity",
        )
    return hashlib.sha256(canonical_event_bytes(canonical_event_record(row))).hexdigest()


def _require_delivered_outbox(conn: sqlite3.Connection) -> None:
    count = int(
        conn.execute("SELECT COUNT(*) FROM outbox_records WHERE status != 'delivered'").fetchone()[0]
    )
    if count:
        raise _Abort(
            "task_accept_projection_pending",
            "A pre-existing JSONL projection is pending.",
            EXIT_RECOVERABLE_PENDING,
            "admission",
            True,
            False,
            "pcl audit flush --json",
        )


def _verify_final_rows_and_events(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    feature_id: str,
    test_ids: list[str],
    evidence_id: str,
    event_plan: list[dict[str, Any]],
) -> None:
    task = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    feature = conn.execute("SELECT status FROM features WHERE id = ?", (feature_id,)).fetchone()
    tests = conn.execute(
        f"SELECT id, status, evidence_id FROM test_cases WHERE id IN ({','.join('?' for _ in test_ids)}) ORDER BY id",
        tuple(test_ids),
    ).fetchall()
    planned_rows = conn.execute(
        f"SELECT id, sequence FROM events WHERE id IN ({','.join('?' for _ in event_plan)}) ORDER BY sequence",
        tuple(str(item["event_id"]) for item in event_plan),
    ).fetchall()
    if (
        task is None
        or task["status"] != "done"
        or feature is None
        or feature["status"] != "done"
        or len(tests) != len(test_ids)
        or any(row["status"] != "passing" or row["evidence_id"] != evidence_id for row in tests)
        or [(str(row["id"]), int(row["sequence"])) for row in planned_rows]
        != [(str(item["event_id"]), int(item["sequence"])) for item in event_plan]
    ):
        raise _Abort(
            "task_accept_post_strict_contract_violation",
            "The sealed final Task acceptance snapshot does not match the plan.",
            EXIT_DATA_ERROR,
            "seal",
        )


def _run_postcommit_render(
    paths: ProjectPaths,
    *,
    operation_capability: object,
    authority_event_id: str,
) -> dict[str, Any]:
    try:
        if not dashboard_auto_render(paths.root):
            return {"status": "disabled", "authority_event_id": authority_event_id}
        _render_dashboard_with_lock(paths, capability=operation_capability)
        return {
            "status": "rendered",
            "authority_event_id": authority_event_id,
            "dashboard_data_sha256": hashlib.sha256(paths.dashboard_data.read_bytes()).hexdigest(),
            "dashboard_html_sha256": hashlib.sha256(paths.dashboard_html.read_bytes()).hexdigest(),
        }
    except Exception:
        return {"status": "pending", "authority_event_id": authority_event_id}


def _verify_replay_render(paths: ProjectPaths, *, identity: dict[str, Any]) -> dict[str, Any]:
    if not dashboard_auto_render(paths.root):
        return {"status": "disabled"}
    try:
        data = json.loads(paths.dashboard_data.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "pending"}
    if not isinstance(data, dict):
        return {"status": "pending"}
    tasks = {
        str(row.get("id")): row
        for row in data.get("tasks", [])
        if isinstance(row, dict)
    }
    features = {
        str(row.get("id")): row
        for row in data.get("features", [])
        if isinstance(row, dict)
    }
    tests = {
        str(row.get("id")): row
        for row in data.get("test_cases", [])
        if isinstance(row, dict)
    }
    if (
        tasks.get(str(identity["task_id"]), {}).get("status") == "done"
        and features.get(str(identity["feature_id"]), {}).get("status") == "done"
        and all(
            tests.get(str(test_id), {}).get("status") == "passing"
            for test_id in identity["test_ids"]
        )
    ):
        return {
            "status": "verified",
            "dashboard_data_sha256": hashlib.sha256(paths.dashboard_data.read_bytes()).hexdigest(),
        }
    return {"status": "pending"}


def _publish_accepted_marker(
    generation: _Generation,
    *,
    request_id: str,
    authority_event_id: str,
    evidence_id: str,
    receipt_sha256: str,
    projection_receipt: dict[str, Any] | None = None,
    render_receipt: dict[str, Any] | None = None,
) -> dict[str, int]:
    del request_id, authority_event_id, evidence_id, receipt_sha256
    del projection_receipt, render_receipt
    return _publish_m2_tail(generation)


def _accepted_marker_value(
    *,
    request_id: str,
    authority_event_id: str,
    evidence_id: str,
    receipt_sha256: str,
) -> dict[str, Any]:
    return {
        "contract_version": "task-accept-accepted-marker/v1",
        "request_id": request_id,
        "authority_event_id": authority_event_id,
        "evidence_id": evidence_id,
        "receipt_sha256": receipt_sha256,
        "state": "accepted",
    }


def _verify_artifact_again(paths: ProjectPaths, artifact: _Artifact) -> None:
    content, binding = secure_read_project_artifact(
        paths,
        artifact.relative_path,
        max_bytes=TASK_ACCEPT_MAX_ARTIFACT_BYTES,
    )
    try:
        if content != artifact.content or hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise _Abort(
                "task_accept_artifact_hash_drift",
                "The acceptance artifact changed during the request.",
                1,
                "artifact_revalidation",
            )
    finally:
        binding.close()


def _task_accept_roots(paths: ProjectPaths) -> dict[str, Path]:
    return {"root": paths.loop_dir / "task-accept-recovery" / "v1"}


def _ensure_directory(path: Path) -> None:
    if path.exists():
        _require_real_directory(path)
        return
    parent = path.parent
    if not parent.exists():
        _ensure_directory(parent)
    _require_real_directory(parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        _require_real_directory(path)


def _require_real_directory(path: Path) -> None:
    try:
        value = os.lstat(path)
    except OSError as exc:
        raise _Abort(
            "task_accept_artifact_publish_failed",
            "A durable Task Accept directory cannot be inspected.",
            EXIT_DATA_ERROR,
            "publish",
        ) from exc
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise _Abort(
            "task_accept_artifact_publish_failed",
            "A durable Task Accept path is not a real directory.",
            EXIT_DATA_ERROR,
            "publish",
        )


def _publish_json_exclusive(path: Path, value: dict[str, Any], *, allow_exact: bool) -> bool:
    return _publish_bytes_exclusive(
        path,
        _canonical_bytes(value) + b"\n",
        allow_exact=allow_exact,
    )


def _publish_bytes_exclusive(path: Path, content: bytes, *, allow_exact: bool) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if not allow_exact:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "A durable Task Accept artifact already exists.",
                EXIT_DATA_ERROR,
                "publish",
            )
        try:
            current = path.read_bytes()
            metadata = os.lstat(path)
        except OSError as exc:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "An existing durable Task Accept artifact cannot be verified.",
                EXIT_DATA_ERROR,
                "publish",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or current != content:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "An existing durable Task Accept artifact is ambiguous.",
                EXIT_DATA_ERROR,
                "publish",
            )
        return False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != content:
            raise OSError("exclusive publish verification failed")
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except Exception as exc:
        raise _Abort(
            "task_accept_artifact_publish_failed",
            "A durable Task Accept artifact could not be published.",
            EXIT_DATA_ERROR,
            "publish",
        ) from exc


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json_required(path)


def _read_json_required(path: Path) -> dict[str, Any]:
    try:
        metadata = os.lstat(path)
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept ledger record is unreadable.",
            EXIT_DATA_ERROR,
            "ledger",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or not isinstance(value, dict):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept ledger record is invalid.",
            EXIT_DATA_ERROR,
            "ledger",
        )
    return value


def _framed_sha256(domain: str, value: dict[str, Any]) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = _canonical_bytes(value)
    framed = (
        b"PCLF1"
        + len(domain_bytes).to_bytes(2, "big")
        + domain_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return hashlib.sha256(framed).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_canonical(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _prefixed_id_sort_key(value: str) -> tuple[int, str]:
    return decimal_sort_key(value.rsplit("-", 1)[1])


def _zero_effects() -> dict[str, int]:
    return {key: 0 for key in sorted(_EFFECT_KEYS)}


def _fresh_effects(
    *,
    event_count: int,
    test_count: int,
    feature_updates: int,
    copies_published: int,
    tail_complete: bool,
    render_writes: int = 0,
) -> dict[str, int]:
    link_count = test_count + 2
    reservation_records = 2 * event_count + 2
    pre_live_records = test_count + 8
    tail_live_records = 5 if tail_complete else 0
    generation_records = 2 if tail_complete else 1
    effects = _zero_effects()
    effects.update(
        {
            "business_attempt_ledger_records_published": generation_records,
            "business_db_rows_inserted": 1 + link_count + 2 * event_count,
            "business_db_rows_updated": test_count + feature_updates + 1,
            "copies_published": copies_published,
            "events_appended": event_count,
            "evidence_links_inserted": link_count,
            "evidence_rows_inserted": 1,
            "feature_status_updates": feature_updates,
            "generation_ledger_records_published": generation_records,
            "live_generation_records_published": pre_live_records + tail_live_records,
            "markers_published": (
                reservation_records
                + pre_live_records
                + tail_live_records
                + generation_records
            ),
            "outbox_records_appended": event_count,
            "projection_records_delivered": event_count if tail_complete else 0,
            "render_writes": render_writes,
            "reservation_index_records_published": reservation_records,
            "tail_db_rows_updated": event_count if tail_complete else 0,
            "task_rows_updated": 1,
            "teardown_receipts_published": 1 if tail_complete else 0,
            "test_rows_updated": test_count,
        }
    )
    effects["db_mutations_total"] = (
        effects["business_db_rows_inserted"]
        + effects["business_db_rows_updated"]
        + effects["tail_db_rows_updated"]
    )
    effects["durable_recovery_records_published"] = effects["markers_published"]
    return effects


def _empty_identity() -> dict[str, Any]:
    return {
        "artifact_locator_sha256": None,
        "feature_id": None,
        "plan_digest": None,
        "pre_accept_prefix_hwm": None,
        "pre_accept_prefix_sha256": None,
        "project_instance_id": None,
        "request_id": None,
        "request_locator": None,
        "task_id": None,
        "test_ids": None,
    }


def _public_identity(identity: dict[str, Any] | None) -> dict[str, Any]:
    if not identity:
        return _empty_identity()
    return {key: identity.get(key) for key in _empty_identity()}


def _empty_authority() -> dict[str, Any]:
    return {
        "acceptance_receipt_sha256": None,
        "event_id": None,
        "prior_authoritative_commit": False,
        "sequence": None,
        "state": "not_established",
    }


def _empty_receipts() -> dict[str, Any]:
    return {
        "acceptance_receipt_status": "not_started",
        "directory_fixture_sha256": None,
        "generation_directory_status": "not_started",
        "projection_status": "not_started",
        "record_fixture_sha256": None,
        "render_status": "not_started",
        "request_binding_status": "not_started",
        "reservation_index_status": "not_started",
        "sealed_head_frame_sha256": None,
        "sqlite_commit_status": "not_started",
        "tail_marker_frame_sha256": None,
        "tail_status": "not_started",
        "teardown_receipt_status": "not_started",
    }


def _empty_validation() -> dict[str, Any]:
    return {
        "current_proof_revalidated": False,
        "current_proof_status": "not_evaluated",
        "evaluated_hwm": None,
        "finding_count": None,
        "findings_sha256": None,
        "origin": None,
        "policy_registry_sha256": None,
        "status": "not_evaluated",
        "terminal_classification": None,
    }


def _validation_contract(
    validation: dict[str, Any] | None,
    *,
    origin: str,
    readiness: dict[str, Any] | None = None,
    current: bool = True,
) -> dict[str, Any]:
    if validation is None:
        return _empty_validation()
    findings = validation.get("findings")
    if not isinstance(findings, list):
        findings = []
    ok = bool(validation.get("ok")) and (readiness is None or bool(readiness.get("terminal_allowed")))
    hwm = None
    if readiness is not None:
        evaluation = readiness.get("evaluation")
        if isinstance(evaluation, dict):
            hwm = evaluation.get("evaluated_through_event_sequence")
        if hwm is None:
            hwm = readiness.get("event_hwm")
            if isinstance(hwm, dict):
                hwm = hwm.get("sequence")
    return {
        "current_proof_revalidated": current,
        "current_proof_status": "healthy" if ok else "unhealthy",
        "evaluated_hwm": hwm,
        "finding_count": len(findings),
        "findings_sha256": _sha256_canonical(findings),
        "origin": origin,
        "policy_registry_sha256": _sha256_canonical(
            {"contract_version": "terminal-readiness/v1", "source": "p0b"}
        ),
        "status": "passed" if ok else "blocked",
        "terminal_classification": (
            "ready"
            if ok
            else "blocked"
        ),
    }


def _complete_teardown(*, rollback: bool) -> dict[str, Any]:
    return {
        "lock_release_attempted": True,
        "lock_released": True,
        "raw_close_attempted": True,
        "raw_close_confirmed": True,
        "registry_invalidated": True,
        "registry_invalidation_attempted": True,
        "rollback_attempted": rollback,
        "rollback_confirmed": True if rollback else None,
        "status": "complete",
    }


def _envelope() -> dict[str, Any]:
    return {
        "authority": _empty_authority(),
        "business_attempt_generation": None,
        "business_changed": False,
        "changed": False,
        "effects": _zero_effects(),
        "error_code": None,
        "exit_code": 0,
        "identity": _empty_identity(),
        "message": "Atomic Task Accept has not started",
        "mode": "precommit_error",
        "mutation_committed": False,
        "ok": False,
        "operation": "task_accept",
        "pending_tail": {
            "detail_sha256": None,
            "outbox_pending_count": 0,
            "render_pending": False,
            "stage": "none",
            "tail_marker_pending": False,
            "teardown_receipt_pending": False,
        },
        "phase": "phase0",
        "prior_acceptance_verified": False,
        "prior_authoritative_commit": False,
        "receipts": _empty_receipts(),
        "safe_retry_action": None,
        "safe_to_retry_original": False,
        "schema_version": TASK_ACCEPT_CONTRACT_VERSION,
        "status": "error",
        "tail_recovery_changed": False,
        "tail_recovery_generation": None,
        "teardown": {
            "lock_release_attempted": False,
            "lock_released": None,
            "raw_close_attempted": False,
            "raw_close_confirmed": None,
            "registry_invalidated": None,
            "registry_invalidation_attempted": False,
            "rollback_attempted": False,
            "rollback_confirmed": None,
            "status": "not_started",
        },
        "validation": _empty_validation(),
    }


def _error_envelope(
    envelope: dict[str, Any],
    *,
    code: str,
    message: str,
    exit_code: int,
    phase: str,
    safe_to_retry_original: bool,
    prior_acceptance_verified: bool = False,
    safe_retry_action: str | None = None,
) -> dict[str, Any]:
    public_identity = _public_identity(envelope.get("identity"))
    identity_values = list(public_identity.values())
    if all(value is None for value in identity_values):
        canonical_phase = "phase0"
    elif (
        all(value is not None for value in identity_values)
        and envelope.get("business_attempt_generation") is not None
        and envelope.get("tail_recovery_generation") is not None
    ):
        canonical_phase = "precommit"
    else:
        canonical_phase = "identity"
    del phase
    envelope.update(
        {
            "error_code": code,
            "exit_code": exit_code,
            "message": message,
            "mode": "precommit_error",
            "mutation_committed": False,
            "ok": False,
            "phase": canonical_phase,
            "prior_acceptance_verified": False,
            "safe_retry_action": safe_retry_action,
            "safe_to_retry_original": False,
            "status": "error",
            "teardown": (
                envelope["teardown"]
                if canonical_phase == "phase0"
                else _complete_teardown(rollback=True)
            ),
        }
    )
    del prior_acceptance_verified
    del safe_to_retry_original
    envelope["identity"] = public_identity
    envelope["business_attempt_generation"] = envelope.get("business_attempt_generation")
    envelope["tail_recovery_generation"] = envelope.get("tail_recovery_generation")
    return envelope


def _postcommit_error(
    envelope: dict[str, Any],
    *,
    code: str,
    message: str,
    identity: dict[str, Any],
    authority_event_id: str | None,
    evidence_id: str | None,
    generation: int,
    action: str,
    business_changed: bool,
    mutation_committed: bool,
    prior_authoritative_commit: bool,
) -> dict[str, Any]:
    prior_authority = envelope.get("authority")
    receipt_sha256 = None
    sequence = None
    if isinstance(prior_authority, dict):
        receipt_sha256 = prior_authority.get("acceptance_receipt_sha256")
        sequence = prior_authority.get("sequence")
    effects = envelope.get("effects")
    if not isinstance(effects, dict) or set(effects) != _EFFECT_KEYS:
        effects = _zero_effects()
    if "projection" in code:
        pending_stage = "projection"
        pending_phase = "projection"
        render_pending = True
    elif "render" in code:
        pending_stage = "render"
        pending_phase = "render"
        render_pending = True
    else:
        pending_stage = "tail_seal"
        pending_phase = "tail_recovery"
        render_pending = False
    envelope.update(
        {
            "authority": {
                "acceptance_receipt_sha256": receipt_sha256,
                "event_id": authority_event_id,
                "prior_authoritative_commit": prior_authoritative_commit,
                "sequence": sequence,
                "state": "verified_prior" if prior_authoritative_commit else "committed_current",
            },
            "business_attempt_generation": generation,
            "business_changed": business_changed,
            "changed": business_changed,
            "effects": effects,
            "error_code": code,
            "exit_code": EXIT_RECOVERABLE_PENDING,
            "identity": _public_identity(identity),
            "message": message,
            "mutation_committed": mutation_committed,
            "ok": False,
            "mode": (
                "accepted_authority_tail_recovery_error"
                if prior_authoritative_commit
                else "fresh_postcommit_tail_error"
            ),
            "pending_tail": {
                "detail_sha256": _sha256_canonical({"code": code, "action": action}),
                "outbox_pending_count": 1 if "projection" in code else 0,
                "render_pending": render_pending,
                "stage": pending_stage,
                "tail_marker_pending": True,
                "teardown_receipt_pending": True,
            },
            "phase": pending_phase,
            "prior_acceptance_verified": prior_authoritative_commit,
            "prior_authoritative_commit": prior_authoritative_commit,
            "safe_retry_action": action,
            "safe_to_retry_original": False,
            "status": "error",
            "teardown": _complete_teardown(rollback=prior_authoritative_commit),
        }
    )
    envelope["changed"] = (
        bool(envelope["business_changed"])
        or bool(envelope["tail_recovery_changed"])
        or int(effects["markers_published"]) > 0
    )
    return envelope


def _commit_outcome_unknown(
    envelope: dict[str, Any],
    *,
    identity: dict[str, Any],
    authority_event_id: str,
    evidence_id: str,
    generation: int,
) -> dict[str, Any]:
    """Report a commit-boundary failure without guessing the durable outcome."""

    action = "process_restart_and_inspect"
    envelope.update(
        {
            "authority": _empty_authority(),
            "business_attempt_generation": generation,
            "business_changed": False,
            "changed": False,
            "error_code": "task_accept_commit_outcome_unknown",
            "exit_code": EXIT_RECOVERABLE_PENDING,
            "identity": _public_identity(identity),
            "message": (
                "The SQLite commit outcome is unknown; do not retry the original "
                "Task acceptance request."
            ),
            "mode": "fresh_postcommit_tail_error",
            "mutation_committed": False,
            "ok": False,
            "pending_tail": {
                "detail_sha256": _sha256_canonical({"code": "task_accept_commit_outcome_unknown"}),
                "outbox_pending_count": 0,
                "render_pending": True,
                "stage": "corrupt",
                "tail_marker_pending": True,
                "teardown_receipt_pending": True,
            },
            "phase": "business_commit",
            "prior_acceptance_verified": False,
            "prior_authoritative_commit": False,
            "safe_retry_action": action,
            "safe_to_retry_original": False,
            "status": "error",
            "teardown": _complete_teardown(rollback=False),
        }
    )
    return envelope


def _internal_serialization_envelope() -> dict[str, Any]:
    envelope = _envelope()
    envelope.update(
        {
            "error_code": "task_accept_internal_error",
            "exit_code": EXIT_DATA_ERROR,
            "message": "Task Accept could not serialize a valid result envelope",
            "safe_retry_action": "manual_integrity_review",
        }
    )
    return envelope


def _stale_generation_envelope(
    *,
    generation: int,
    identity: dict[str, Any],
) -> dict[str, Any]:
    envelope = _envelope()
    effects = _zero_effects()
    effects.update(
        {
            "business_attempt_ledger_records_published": 1,
            "durable_recovery_records_published": 1,
            "generation_ledger_records_published": 1,
            "markers_published": 1,
        }
    )
    envelope.update(
        {
            "business_attempt_generation": generation,
            "changed": True,
            "effects": effects,
            "error_code": "task_accept_business_attempt_generation_advanced",
            "exit_code": EXIT_RECOVERABLE_PENDING,
            "identity": _public_identity(identity),
            "message": "A new business attempt generation was reserved; repeat the exact request",
            "mode": "stale_precommit_generation_advanced",
            "phase": "precommit",
            "receipts": {
                **_empty_receipts(),
                "generation_directory_status": "partial",
            },
            "safe_retry_action": "repeat_exact_task_accept_request",
            "safe_to_retry_original": True,
            "status": "retry_required",
            "tail_recovery_generation": 0,
            "teardown": _complete_teardown(rollback=True),
        }
    )
    return envelope


def _tail_recovery_success_envelope(
    *,
    identity: dict[str, Any],
    receipt: dict[str, Any],
    authority_row: sqlite3.Row,
    generation: _Generation,
    event_count: int,
    render_receipt: dict[str, Any],
    validation: dict[str, Any],
    readiness: dict[str, Any],
    markers_published: int = 6,
) -> dict[str, Any]:
    record_set = _m2_record_set_receipts(generation)
    effects = _zero_effects()
    effects.update(
        {
            "db_mutations_total": event_count,
            "durable_recovery_records_published": markers_published,
            "generation_ledger_records_published": 1,
            "live_generation_records_published": markers_published - 1,
            "markers_published": markers_published,
            "projection_records_delivered": event_count,
            "render_writes": 0 if render_receipt["status"] == "disabled" else 1,
            "tail_db_rows_updated": event_count,
            "tail_recovery_ledger_records_published": 1,
            "teardown_receipts_published": 1,
        }
    )
    envelope = _envelope()
    envelope.update(
        {
            "authority": {
                "acceptance_receipt_sha256": _sha256_canonical(receipt),
                "event_id": str(authority_row["id"]),
                "prior_authoritative_commit": True,
                "sequence": int(authority_row["sequence"]),
                "state": "verified_prior",
            },
            "business_attempt_generation": generation.number,
            "changed": True,
            "effects": effects,
            "exit_code": 0,
            "identity": _public_identity(identity),
            "message": f"Accepted Task {identity['task_id']} tail recovered",
            "mode": "accepted_authority_tail_recovery_success",
            "mutation_committed": False,
            "ok": True,
            "phase": "complete",
            "prior_acceptance_verified": True,
            "prior_authoritative_commit": True,
            "receipts": {
                "acceptance_receipt_status": "prior_verified",
                "directory_fixture_sha256": record_set["directory_fixture_sha256"],
                "generation_directory_status": "recovered",
                "projection_status": "delivered",
                "record_fixture_sha256": record_set["record_fixture_sha256"],
                "render_status": "disabled" if render_receipt["status"] == "disabled" else "current",
                "request_binding_status": "prior_verified",
                "reservation_index_status": "prior_verified",
                "sealed_head_frame_sha256": record_set["sealed_head_frame_sha256"],
                "sqlite_commit_status": "prior_committed",
                "tail_marker_frame_sha256": record_set["tail_marker_frame_sha256"],
                "tail_status": "complete",
                "teardown_receipt_status": "published",
            },
            "status": "recovered",
            "tail_recovery_changed": True,
            "tail_recovery_generation": 1,
            "teardown": _complete_teardown(rollback=True),
            "validation": _validation_contract(
                validation,
                origin="tail_recovery_live_revalidation",
                readiness=readiness,
            ),
        }
    )
    return envelope


def _tail_recovery_blocked_envelope(
    *,
    identity: dict[str, Any],
    receipt: dict[str, Any],
    authority_row: sqlite3.Row,
    validation: dict[str, Any],
    readiness: dict[str, Any],
    code: str = "task_accept_terminal_readiness_failed",
    message: str | None = None,
) -> dict[str, Any]:
    envelope = _envelope()
    envelope.update(
        {
            "authority": {
                "acceptance_receipt_sha256": _sha256_canonical(receipt),
                "event_id": str(authority_row["id"]),
                "prior_authoritative_commit": True,
                "sequence": int(authority_row["sequence"]),
                "state": "verified_prior",
            },
            "business_attempt_generation": 0,
            "error_code": code,
            "exit_code": EXIT_RECOVERABLE_PENDING,
            "identity": _public_identity(identity),
            "message": message or f"Accepted Task {identity['task_id']} no longer passes terminal readiness",
            "mode": "accepted_authority_tail_recovery_error",
            "pending_tail": {
                "detail_sha256": _sha256_canonical(readiness),
                "outbox_pending_count": 0,
                "render_pending": True,
                "stage": "tail_seal",
                "tail_marker_pending": True,
                "teardown_receipt_pending": True,
            },
            "phase": "tail_recovery",
            "prior_acceptance_verified": True,
            "prior_authoritative_commit": True,
            "receipts": {
                **_empty_receipts(),
                "acceptance_receipt_status": "prior_verified",
                "generation_directory_status": "partial",
                "projection_status": "prior_delivered",
                "request_binding_status": "prior_verified",
                "reservation_index_status": "prior_verified",
                "sqlite_commit_status": "prior_committed",
                "tail_status": "pending",
                "teardown_receipt_status": "pending",
            },
            "safe_retry_action": "pcl audit flush --json",
            "status": "error",
            "tail_recovery_generation": 0,
            "teardown": _complete_teardown(rollback=True),
            "validation": _validation_contract(
                validation,
                origin="tail_recovery_live_revalidation",
                readiness=readiness,
            ),
        }
    )
    return envelope
