from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the local read-only Vivi voice benchmark dashboard."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()
    os.environ["VIVI_DASHBOARD_RESULTS_DIR"] = args.results_dir
    uvicorn.run(
        "src.dashboard.app:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        app_dir=".",
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
