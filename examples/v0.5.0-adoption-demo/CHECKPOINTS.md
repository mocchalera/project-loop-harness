# Expected checkpoints

The run is successful only when every checkpoint below is visible.

| Checkpoint | Expected result | Why it matters |
| --- | --- | --- |
| Distribution | `pcl 0.5.0` | Proves the public wheel, not checkout source, is running. |
| Inspect-first init | dry-run JSON has `ok: true`; init and doctor succeed | Shows the adoption boundary before mutation. |
| Intent receipt | `G-0001`, `T-0001`, and the full Japanese intent appear in `pcl-start/v1` | Preserves what “done” is supposed to mean. |
| Acceptance | `Ran 1 test` and `OK` | Gives a replayable behavior check. |
| Evidence | `E-0002`, `storage_mode: copied`, a SHA-256, and `linked_task_id: T-0001` | Pins the exact review artifact and its target. |
| Completion packet | `outcome: COMPLETED_VERIFIED`, passed `git diff --check`, and strict validation `ok: true` | Binds guarded checks and repository snapshot to completion. |
| Goal close | `status: closed`, `proof_type: completion_packet` | Prevents an unsupported “done” claim. |
| Final health | strict validation has no errors or warnings | Confirms lifecycle consistency. |
| Human view | render returns `dashboard.html`; the browser shows Japanese chrome | Keeps presentation separate from machine state. |
| Stop condition | final action has `type: idle`, `command: null` | Demonstrates an explicit safe stop. |

The final summary also prints stable labels suitable for CI assertions:

```text
DEMO_OK=1
PCL_VERSION=0.5.0
PACKET_OUTCOME=COMPLETED_VERIFIED
NEXT_TYPE=idle
```

IDs are deterministic in this fresh target, but the script parses returned
JSON instead of relying on hard-coded IDs.
