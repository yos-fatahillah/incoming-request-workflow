"""
run_batch_demo.py
------------------
Command-line batch demo: processes the full sample dataset end-to-end
(classify -> branch -> remediate -> log) and prints a readable trace for
each case, plus a final summary. Useful for quick verification, screenshots,
and as the "optional enhancement: batch processing" deliverable.

Usage:
    python run_batch_demo.py
"""

import os
import sys
from classifier import classify_request
from workflows import run_workflow
from storage import log_case, summary_counts, DB_PATH
from sample_data import SAMPLE_REQUESTS


def process_one(req):
    classification = classify_request(req["text"])
    result = run_workflow(req["id"], req["text"], classification)
    log_case(req["id"], req["text"], classification, result)
    return classification, result


def print_case(req, classification, result):
    print("=" * 78)
    print(f"[{req['id']}] \"{req['text'][:90]}{'...' if len(req['text']) > 90 else ''}\"")
    print("-" * 78)
    print(f"  Classification : {classification['request_type']}  "
          f"(urgency={classification['urgency']}, confidence={classification['confidence']}, "
          f"engine={classification['engine']})")
    print(f"  Sub-topic      : {classification.get('sub_topic')}")
    print(f"  Key details    : {classification.get('key_details')}")
    if result.get("override_applied"):
        print(f"  >>> ESCALATION OVERRIDE APPLIED: {result['override_reason']}")
    print(f"  Branch executed: {result['branch']}")
    print("  Steps:")
    for i, step in enumerate(result["steps"], 1):
        print(f"    {i}. {step['step']} -> {step['status']}")
        print(f"       {step['detail']}")
    print("  Outputs:")
    for k, v in result["outputs"].items():
        v_str = str(v)
        print(f"    - {k}: {v_str[:150]}{'...' if len(v_str) > 150 else ''}")
    print()


def main():
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(">> Running with LIVE Claude API classification & drafting.\n")
    else:
        print(">> No ANTHROPIC_API_KEY set — running with offline keyword-fallback engine.\n"
              "   (Set ANTHROPIC_API_KEY to see live Claude-powered classification & drafting.)\n")

    # fresh DB for a clean demo run
    if DB_PATH.exists():
        DB_PATH.unlink()

    for req in SAMPLE_REQUESTS:
        classification, result = process_one(req)
        print_case(req, classification, result)

    summary = summary_counts()
    print("=" * 78)
    print("SUMMARY DASHBOARD")
    print("-" * 78)
    print(f"  Total requests processed : {summary['total']}")
    print(f"  By type    : {summary['by_type']}")
    print(f"  By urgency : {summary['by_urgency']}")
    print(f"  Overrides  : {summary['by_override']}")
    print("=" * 78)


if __name__ == "__main__":
    sys.exit(main())
