#!/bin/bash
# Helper script to create and run a request through all gates
# Usage: ./create_request.sh <REQUEST_ID> "<objective>" "<constraints>" "<non_goals>" "<definition_of_done>"

set -euo pipefail

BASE="$REPO_ROOT"
REQ="${1:-TEST-$(date +%s)}"
OBJ="${2:-Create a simple project}"
CONS="${3:-Standard practices}"
NON="${4:-No GUI}"
DOD="${5:-Project works}"

echo "Creating request: $REQ"
echo "Objective: $OBJ"
echo ""

# Convert to JSON
OBJ_JSON=$(python3 -c "import json; print(json.dumps('$OBJ'))")
CONS_JSON=$(python3 -c "import json; print(json.dumps([x.strip() for x in '$CONS'.split(',')]))")
NON_JSON=$(python3 -c "import json; print(json.dumps([x.strip() for x in '$NON'.split(',')]))")
DOD_JSON=$(python3 -c "import json; print(json.dumps([x.strip() for x in '$DOD'.split(',')]))")

# Gate 0: Init
echo "=== Gate 0: Init ==="
python3 "$BASE/orchestrator/orchestrator.py" gate0_init "$REQ" "$OBJ_JSON" "$CONS_JSON" "$NON_JSON" "$DOD_JSON"

# Gate 1: Planning
echo ""
echo "=== Gate 1: Planning ==="
python3 "$BASE/orchestrator/orchestrator.py" gate1_planning "$REQ"

# Gate 2: Delegation
echo ""
echo "=== Gate 2: Delegation ==="
python3 "$BASE/orchestrator/orchestrator.py" gate2_delegation "$REQ"

# Gate 3: Execution
echo ""
echo "=== Gate 3: Execution ==="
python3 "$BASE/orchestrator/orchestrator.py" gate3_execution "$REQ"

# Gate 4: Review
echo ""
echo "=== Gate 4: Review ==="
python3 "$BASE/orchestrator/orchestrator.py" gate4_review "$REQ"

# Gate 5: Finalize
echo ""
echo "=== Gate 5: Finalize ==="
python3 "$BASE/orchestrator/orchestrator.py" gate5_finalize "$REQ"

# Gate 6: Complete
echo ""
echo "=== Gate 6: Complete ==="
python3 "$BASE/orchestrator/orchestrator.py" gate6_complete "$REQ"

echo ""
echo "=== Summary ==="
echo "Request ID: $REQ"
echo "Location: $BASE/state/requests/$REQ"
echo ""
echo "Gate Statuses:"
for g in 0 1 2 3 4 5 6; do
    echo -n "  gate$g: "
    cat "$BASE/state/requests/$REQ/gate$g.status" 2>/dev/null || echo "NOT_RUN"
done

echo ""
echo "Project files:"
find "$BASE/state/requests/$REQ/workspace/project" -type f 2>/dev/null | head -10 || echo "  (none)"

echo ""
echo "Dist artifacts:"
ls -lh "$BASE/state/requests/$REQ/dist/" 2>/dev/null | tail -5 || echo "  (none)"

