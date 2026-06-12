from __future__ import annotations

import argparse
import json

from src.fdrc_run_inspector import (
    benchmark_report,
    compare_layers,
    debug_rows,
    format_debug_table,
    write_benchmark_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Debug a Full-Duplex Repair-to-Commit benchmark run end-to-end."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    if args.compare:
        payload = compare_layers(args.run_id, args.results_dir)
    elif args.json:
        payload = benchmark_report(args.run_id, args.results_dir)
    else:
        payload = None
        print(format_debug_table(debug_rows(args.run_id, args.results_dir)))

    if payload is not None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.write_report:
        json_path, md_path = write_benchmark_report(
            args.run_id,
            args.results_dir,
            args.output_dir,
        )
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
