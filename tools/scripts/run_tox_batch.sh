#!/bin/bash

# Script to run tox -e py312 twenty times and summarize failures
# Usage: ./run_tox_batch.sh

set -e

RUNS=40
FAILED_RUNS=()
FAILED_FILES=()
SUCCESS_COUNT=0
TOTAL_RUNS=0
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo "Running tox -e py312 ${RUNS} times..."
echo "Started at: $(date)"
echo ""

for i in $(seq 1 $RUNS); do
    echo -n "Run $i/$RUNS... "

    # Create temporary file for this run's output
    TEMP_FILE=$(mktemp)

    # Run tox and capture both stdout and stderr to temp file
    if tox -e py312 >"$TEMP_FILE" 2>&1; then
        echo "✓ PASSED"
        # Clean up temp file on success
        rm "$TEMP_FILE"
        ((SUCCESS_COUNT++))
    else
        echo "✗ FAILED"
        # Move temp file to permanent location with meaningful name
        FAILED_FILE="run_tox_batch_output_${TIMESTAMP}_run_${i}.txt"
        mv "$TEMP_FILE" "$FAILED_FILE"
        FAILED_RUNS+=($i)
        FAILED_FILES+=("$FAILED_FILE")
        echo "    Output saved to: $FAILED_FILE"
    fi

    ((TOTAL_RUNS++))
done

echo ""
echo "========================================="
echo "SUMMARY"
echo "========================================="
echo "Total runs: $TOTAL_RUNS"
echo "Successful runs: $SUCCESS_COUNT"
echo "Failed runs: $((TOTAL_RUNS - SUCCESS_COUNT))"

if [ ${#FAILED_RUNS[@]} -eq 0 ]; then
    echo ""
    echo "🎉 ALL RUNS PASSED!"
else
    echo ""
    echo "❌ FAILED RUNS:"
    for i in "${!FAILED_RUNS[@]}"; do
        run="${FAILED_RUNS[$i]}"
        file="${FAILED_FILES[$i]}"
        echo "  - Run #$run: Output saved to $file"
    done

    echo ""
    echo "To investigate failures, examine the output files above or run:"
    echo "  tox -e py312"
    echo ""
    echo "Example: cat ${FAILED_FILES[0]:-run_tox_batch_output_<timestamp>_run_<N>.txt}"
fi

echo ""
echo "Completed at: $(date)"

# Exit with error code if any runs failed
if [ ${#FAILED_RUNS[@]} -ne 0 ]; then
    exit 1
fi
