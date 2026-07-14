#!/usr/bin/env bash
set -Eeuo pipefail

KEEP=0
PACED=0

usage() {
  cat <<'EOF'
Usage: ./run-demo.sh [--keep] [--paced]

  --keep    Keep the isolated temporary directory so the dashboard can be opened.
  --paced   Pause briefly between checkpoints for a narrated recording.

The script installs project-loop-harness==0.5.0 from PyPI into a new venv.
It never writes to the source repository's .project-loop, .claude, or pcl.yaml.
EOF
}

while (($#)); do
  case "$1" in
    --keep) KEEP=1 ;;
    --paced) PACED=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for command in python3 git; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"
WORK_ROOT="$(mktemp -d "$TMP_BASE/pcl-v0.5.0-demo.XXXXXX")"
MARKER="$WORK_ROOT/.pcl-v0.5.0-demo-owned"
PROJECT="$WORK_ROOT/project"
VENV="$WORK_ROOT/venv"
START_SECONDS="$(date +%s)"
touch "$MARKER"

cleanup() {
  status=$?
  if ((status != 0)); then
    KEEP=1
    printf '\nFAILED (exit %s). Kept diagnostic workspace: %s\n' "$status" "$WORK_ROOT" >&2
  fi
  if ((KEEP == 0)); then
    case "$WORK_ROOT" in
      "$TMP_BASE"/pcl-v0.5.0-demo.*)
        if [[ -f "$MARKER" ]]; then
          rm -rf -- "$WORK_ROOT"
        fi
        ;;
      *)
        printf 'Refusing to clean unexpected path: %s\n' "$WORK_ROOT" >&2
        ;;
    esac
  fi
}
trap cleanup EXIT

stage() {
  printf '\n\033[1;36m[%s]\033[0m %s\n' "$1" "$2"
  if ((PACED == 1)); then sleep 1; fi
}

json_value() {
  "$PYTHON" -c 'import json, sys
data = json.load(sys.stdin)
for key in sys.argv[1:]:
    data = data[key]
print(data)' "$@"
}

mkdir -p "$PROJECT"
cp -R "$SCRIPT_DIR/seed/." "$PROJECT/"

stage "0:00" "公開 PyPI 版をクリーンな venv に固定インストール"
python3 -m venv "$VENV"
PYTHON="$VENV/bin/python"
PCL="$VENV/bin/pcl"
PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON" -m pip install --quiet --no-cache-dir \
  project-loop-harness==0.5.0
"$PCL" --version

stage "0:25" "非空プロジェクトを dry-run で確認してから init"
"$PCL" init --target "$PROJECT" --dry-run --json
"$PCL" init --target "$PROJECT"

# Configure only the disposable target project. The source repository's
# pcl.yaml is never read by this script and is never modified.
"$PYTHON" - "$PROJECT/pcl.yaml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
replacements = {
    '  name: "CHANGE_ME"': '  name: "pcl-v0.5.0-adoption-demo"',
    '  install: ""': '  install: null',
    '  lint: ""': '  lint: null',
    '  typecheck: ""': '  typecheck: null',
    '  test: ""': '  test: "git diff --check"',
    '  e2e: ""': '  e2e: null',
    '  build: ""': '  build: null',
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"unexpected generated pcl.yaml entry: {old}")
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
PY

cd "$PROJECT"
git init -q -b main
git add .
git -c user.name="PCL Demo" -c user.email="demo@example.invalid" \
  commit -q -m "chore: seed isolated demo target"
"$PCL" --json doctor

stage "0:55" "自然言語 intent をそのまま Goal / Task として開始"
INTENT="demo-result.txt に受け入れ済みの結果を残し、再現可能な検証証拠とともに完了する"
START_JSON="$("$PCL" --json start "$INTENT")"
printf '%s\n' "$START_JSON"
GOAL_ID="$(printf '%s' "$START_JSON" | json_value result created_ids goal)"
TASK_ID="$(printf '%s' "$START_JSON" | json_value result created_ids task)"

stage "1:15" "成果を作り、stdlib の受け入れテストを実行"
printf '%s\n' 'PLH v0.5.0 adoption demo: PASS' > demo-result.txt
mkdir -p artifacts
"$PYTHON" -m unittest discover -s tests -v 2>&1 | tee artifacts/acceptance.txt

stage "1:40" "テスト出力を SHA-256 固定の Evidence として Task に登録"
EVIDENCE_JSON="$("$PCL" --json evidence add \
  --file artifacts/acceptance.txt \
  --summary "受け入れコマンドが PASS した出力" \
  --command "python -m unittest discover -s tests -v" \
  --copy \
  --task "$TASK_ID")"
printf '%s\n' "$EVIDENCE_JSON"
EVIDENCE_ID="$(printf '%s' "$EVIDENCE_JSON" | json_value evidence id)"
"$PCL" --json task status "$TASK_ID" done \
  --reason "$EVIDENCE_ID の受け入れ結果を確認"

stage "2:00" "guarded check と strict validation で completion packet を発行"
FINISH_JSON="$("$PCL" --json finish --emit-packet --goal "$GOAL_ID")"
printf '%s\n' "$FINISH_JSON"
PACKET_EVIDENCE_ID="$(printf '%s' "$FINISH_JSON" | json_value finish packet evidence_id)"
PACKET_OUTCOME="$(printf '%s' "$FINISH_JSON" | json_value finish packet outcome)"
if [[ "$PACKET_OUTCOME" != "COMPLETED_VERIFIED" ]]; then
  printf 'Unexpected completion outcome: %s\n' "$PACKET_OUTCOME" >&2
  exit 1
fi
"$PCL" --json goal close "$GOAL_ID" \
  --summary "goal-bound completion packet により検証済みで完了" \
  --evidence-id "$PACKET_EVIDENCE_ID"

stage "2:30" "strict validation 後、日本語ダッシュボードを生成"
"$PCL" --json validate --strict
RENDER_JSON="$("$PCL" --json render --locale ja)"
printf '%s\n' "$RENDER_JSON"
NEXT_JSON="$("$PCL" --json next)"
printf '%s\n' "$NEXT_JSON"
NEXT_TYPE="$(printf '%s' "$NEXT_JSON" | json_value type)"
if [[ "$NEXT_TYPE" != "idle" ]]; then
  printf 'Expected idle next action, got: %s\n' "$NEXT_TYPE" >&2
  exit 1
fi

ELAPSED_SECONDS="$(( $(date +%s) - START_SECONDS ))"
DASHBOARD="$PROJECT/.project-loop/dashboard/dashboard.html"
printf '\nDEMO_OK=1\n'
printf 'PCL_VERSION=0.5.0\n'
printf 'GOAL_ID=%s\nTASK_ID=%s\n' "$GOAL_ID" "$TASK_ID"
printf 'ACCEPTANCE_EVIDENCE_ID=%s\n' "$EVIDENCE_ID"
printf 'PACKET_EVIDENCE_ID=%s\nPACKET_OUTCOME=%s\n' \
  "$PACKET_EVIDENCE_ID" "$PACKET_OUTCOME"
printf 'NEXT_TYPE=%s\nELAPSED_SECONDS=%s\n' "$NEXT_TYPE" "$ELAPSED_SECONDS"
printf 'DASHBOARD=%s\n' "$DASHBOARD"
if ((KEEP == 1)); then
  printf 'WORK_ROOT=%s\n' "$WORK_ROOT"
else
  printf 'Workspace will be removed; rerun with --keep to inspect the dashboard.\n'
fi
