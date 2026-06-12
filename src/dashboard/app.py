from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .service import DashboardStore, RunNotFound


STATIC_DIR = Path(__file__).resolve().parent / "static"


class BenchmarkRunRequest(BaseModel):
    preset_id: str
    domains: str = "automotive,navigation,media_phone"
    personas: str = "vi_north_normal,vi_central_normal,vi_south_normal"
    model: str | None = None


def create_app(results_dir: str = "results") -> FastAPI:
    results_dir = os.environ.get("VIVI_DASHBOARD_RESULTS_DIR", results_dir)
    app = FastAPI(title="Vivi Voice Benchmark Dashboard")
    store = DashboardStore(Path(results_dir))

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return store.list_runs()

    @app.get("/api/run-presets")
    def run_presets() -> list[dict[str, Any]]:
        return store.run_presets()

    @app.get("/api/dashboard-config")
    def dashboard_config() -> dict[str, Any]:
        return store.dashboard_config()

    @app.post("/api/benchmark-runs")
    def start_benchmark_run(request: BenchmarkRunRequest) -> dict[str, Any]:
        try:
            return store.start_benchmark_run(
                request.preset_id,
                domains=request.domains,
                personas=request.personas,
                model=request.model,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/benchmark-runs/{job_id}")
    def benchmark_run_status(job_id: str) -> dict[str, Any]:
        try:
            return store.job_status(job_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/summary")
    def run_summary(run_id: str, track: str | None = None) -> dict[str, Any]:
        try:
            return store.run_summary(run_id, track=track)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/episodes")
    def list_episodes(
        run_id: str,
        track: str | None = None,
        domain: str | None = None,
        mode: str | None = None,
        failure: str | None = None,
        passed: bool | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return store.list_episodes(
                run_id,
                track=track,
                domain=domain,
                mode=mode,
                failure=failure,
                passed=passed,
            )
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/episodes/{episode_id}")
    def episode_detail(run_id: str, episode_id: str) -> dict[str, Any]:
        try:
            detail = store.episode_detail(run_id, episode_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if detail is None:
            raise HTTPException(status_code=404, detail="Episode not found")
        return detail

    return app
