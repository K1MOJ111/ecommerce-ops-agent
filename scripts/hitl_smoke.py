"""Run the real PostgreSQL smoke scenarios, reusing the isolated integration fixtures."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

SCENARIOS = {
    "hitl": ["test_confirm_and_repeat_are_stable", "test_reject_writes_only_receipt_and_audit"],
    "restart": ["test_restart_new_engine_and_model_without_memory", "test_api_restart_and_security", "test_restart_resume_in_separate_process"],
    "concurrency": ["test_concurrent_confirm_independent_connections", "test_concurrent_different_operations_cannot_over_refund",
                    "test_business_row_lock_idempotency_without_graph_lock", "test_same_order_different_item_refund_race"],
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=[*SCENARIOS, "all"], default="all", nargs="?")
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("TEST_DATABASE_URL is required; a skipped test is not a smoke pass.")
    names = [name for group in SCENARIOS.values() for name in group] if args.mode == "all" else SCENARIOS[args.mode]
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", "tests/integration/test_hitl.py", "-k", " or ".join(names)],
                                     cwd=Path(__file__).resolve().parents[1]))
