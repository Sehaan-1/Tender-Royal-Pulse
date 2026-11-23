from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from tender_royal_pulse.cli_helpers import build_row_processor, resolve_db
from tender_royal_pulse.crawler import (
    CrawlEngine,
    ListPagePayload,
    create_run,
    create_tasks,
)
from tender_royal_pulse.web.seeder import seed_database_from_samples

_log = logging.getLogger("tender_royal_pulse.web")


class CrawlRequest(BaseModel):
    date_from: str = "2026-04-01"
    date_to: str = "2026-05-05"
    tender_type: str = "all"
    pages_limit: int = 5
    mode: str = "mock"


def get_db_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_app(db_path: str = "data/tenderpulse.db") -> FastAPI:
    app = FastAPI(title="TenderPulse Intelligence Engine UI", version="0.1.0")

    # Ensure DB and seed if empty
    resolved_path = Path(db_path)
    conn = resolve_db(resolved_path)
    tender_count = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    conn.close()
    if tender_count == 0:
        seed_database_from_samples(resolved_path)

    # -----------------------------------------------------------------------
    # API Routes
    # -----------------------------------------------------------------------

    @app.get("/api/stats")
    def get_stats() -> dict[str, Any]:
        conn = get_db_connection(db_path)
        try:
            total_tenders = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
            val_row = conn.execute("SELECT SUM(tender_value), AVG(tender_value) FROM tenders WHERE tender_value IS NOT NULL").fetchone()
            total_value = val_row[0] or 0.0
            avg_value = val_row[1] or 0.0

            total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

            task_status_rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
            ).fetchall()
            task_status = {r["status"]: r["cnt"] for r in task_status_rows}

            # Category breakdown
            cat_rows = conn.execute(
                "SELECT COALESCE(category, 'Uncategorized') as cat, COUNT(*) as cnt "
                "FROM tenders GROUP BY cat ORDER BY cnt DESC LIMIT 6"
            ).fetchall()
            category_distribution = [{"category": r["cat"], "count": r["cnt"]} for r in cat_rows]

            # Top organizations
            org_rows = conn.execute(
                "SELECT COALESCE(org_chain, 'Direct / General') as org, COUNT(*) as cnt "
                "FROM tenders GROUP BY org ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            top_organizations = [{"org": r["org"], "count": r["cnt"]} for r in org_rows]

            return {
                "total_tenders": total_tenders,
                "total_value": total_value,
                "avg_value": avg_value,
                "total_runs": total_runs,
                "total_tasks": total_tasks,
                "task_status": {
                    "PENDING": task_status.get("PENDING", 0),
                    "RUNNING": task_status.get("RUNNING", 0),
                    "DONE": task_status.get("DONE", 0),
                    "FAILED_RETRYABLE": task_status.get("FAILED_RETRYABLE", 0),
                    "FAILED_PERMANENT": task_status.get("FAILED_PERMANENT", 0),
                },
                "category_distribution": category_distribution,
                "top_organizations": top_organizations,
            }
        finally:
            conn.close()

    @app.get("/api/tenders")
    def get_tenders(
        q: str | None = None,
        category: str | None = None,
        tender_type: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = Query(1, ge=1),
        page_size: int = Query(15, ge=1, le=100),
    ) -> dict[str, Any]:
        conn = get_db_connection(db_path)
        try:
            query_parts = ["1=1"]
            params: list[Any] = []

            if q:
                pattern = f"%{q.strip()}%"
                query_parts.append(
                    "(title LIKE ? OR tender_id LIKE ? OR reference_number LIKE ? OR org_chain LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])

            if category and category != "all":
                query_parts.append("category = ?")
                params.append(category)

            if tender_type and tender_type != "all":
                query_parts.append("tender_type = ?")
                params.append(tender_type)

            if min_value is not None:
                query_parts.append("tender_value >= ?")
                params.append(min_value)

            if max_value is not None:
                query_parts.append("tender_value <= ?")
                params.append(max_value)

            where_clause = " AND ".join(query_parts)

            # Count total matching
            count_sql = f"SELECT COUNT(*) FROM tenders WHERE {where_clause}"
            total = conn.execute(count_sql, params).fetchone()[0]

            allowed_sorts = {
                "created_at": "created_at",
                "tender_value": "tender_value",
                "closing_date": "closing_date",
                "published_date": "published_date",
                "title": "title",
            }
            order_col = allowed_sorts.get(sort_by, "created_at")
            order_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

            offset = (page - 1) * page_size
            data_sql = f"""
                SELECT id, source, tender_id, title, reference_number, org_chain,
                       tender_type, category, tender_value, emd_amount, doc_fee,
                       closing_date, opening_date, published_date, detail_url, created_at
                FROM tenders
                WHERE {where_clause}
                ORDER BY {order_col} {order_dir}
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(data_sql, [*params, page_size, offset]).fetchall()

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size if page_size else 1,
                "items": [dict(r) for r in rows],
            }
        finally:
            conn.close()

    @app.get("/api/tenders/{tender_id}")
    def get_tender_detail(tender_id: str) -> dict[str, Any]:
        conn = get_db_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM tenders WHERE tender_id = ? OR id = ?",
                (tender_id, tender_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tender not found")
            res = dict(row)
            if res.get("raw_json"):
                try:
                    res["raw_data"] = json.loads(res["raw_json"])
                except Exception:
                    res["raw_data"] = None
            return res
        finally:
            conn.close()

    @app.get("/api/runs")
    def get_runs() -> list[dict[str, Any]]:
        conn = get_db_connection(db_path)
        try:
            runs = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 20").fetchall()
            out: list[dict[str, Any]] = []
            for r in runs:
                run_id = r["id"]
                counts = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM tasks WHERE run_id = ? GROUP BY status",
                    (run_id,),
                ).fetchall()
                task_summary = {c["status"]: c["cnt"] for c in counts}
                total = sum(task_summary.values())
                done = task_summary.get("DONE", 0)
                running = task_summary.get("RUNNING", 0)
                pending = task_summary.get("PENDING", 0)
                failed = task_summary.get("FAILED_RETRYABLE", 0) + task_summary.get("FAILED_PERMANENT", 0)

                out.append({
                    "id": run_id,
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "tasks_total": total,
                    "tasks_done": done,
                    "tasks_running": running,
                    "tasks_pending": pending,
                    "tasks_failed": failed,
                })
            return out
        finally:
            conn.close()

    @app.get("/api/runs/{run_id}/tasks")
    def get_run_tasks(run_id: str) -> list[dict[str, Any]]:
        conn = get_db_connection(db_path)
        try:
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            return [dict(t) for t in tasks]
        finally:
            conn.close()

    def _execute_crawl_background(run_id: str, pages_limit: int, mode: str) -> None:
        try:
            resolve_db(Path(db_path))
            engine = CrawlEngine(
                db_path,
                row_processor=build_row_processor("mock"),
                log_level=logging.INFO,
            )
            engine.process_run(run_id)
        except Exception as e:
            _log.error(f"Error in background crawl {run_id}: {e}", exc_info=True)

    @app.post("/api/crawl")
    def start_crawl(payload: CrawlRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        conn = resolve_db(Path(db_path))
        run_id = create_run(conn)

        date_filter = f"{payload.date_from},{payload.date_to}"
        page_payloads = [
            ListPagePayload(
                mode="closing_today",
                page_index=i,
                date_filter=date_filter,
            )
            for i in range(1, payload.pages_limit + 1)
        ]

        tasks = create_tasks(conn, run_id, page_payloads)
        conn.close()

        background_tasks.add_task(_execute_crawl_background, run_id, payload.pages_limit, payload.mode)

        return {
            "status": "started",
            "run_id": run_id,
            "tasks_count": len(tasks),
            "message": f"Crawl run {run_id[:8]} started with {len(tasks)} page tasks",
        }

    @app.post("/api/seed")
    def trigger_seed() -> dict[str, Any]:
        count = seed_database_from_samples(db_path)
        return {"status": "ok", "seeded_count": count}

    @app.get("/api/export")
    def export_data(format: str = "csv") -> StreamingResponse:
        conn = get_db_connection(db_path)
        try:
            rows = conn.execute("SELECT * FROM tenders ORDER BY created_at DESC").fetchall()
            if format == "jsonl":
                stream = io.StringIO()
                for r in rows:
                    rec = dict(r)
                    stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stream.seek(0)
                return StreamingResponse(
                    iter([stream.getvalue()]),
                    media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=tenders_export.jsonl"},
                )
            else:
                stream = io.StringIO()
                if rows:
                    fieldnames = [c for c in rows[0].keys() if c != "raw_json"]
                    writer = csv.DictWriter(stream, fieldnames=fieldnames)
                    writer.writeheader()
                    for r in rows:
                        row_dict = {k: r[k] for k in fieldnames}
                        writer.writerow(row_dict)
                stream.seek(0)
                return StreamingResponse(
                    iter([stream.getvalue()]),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=tenders_export.csv"},
                )
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Main Dashboard Single Page Application
    # -----------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index_page() -> str:
        return DASHBOARD_HTML

    return app


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TenderPulse · eProcure Intelligence & Crawler UI</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/lucide@latest"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['"Plus Jakarta Sans"', 'sans-serif'],
            mono: ['"JetBrains Mono"', 'monospace'],
          },
          colors: {
            brand: {
              50: '#f0fdf4',
              100: '#dcfce7',
              500: '#22c55e',
              600: '#16a34a',
              700: '#15803d',
              900: '#14532d',
            },
            slate: {
              850: '#151e2e',
              900: '#0f172a',
              950: '#090d16',
            }
          }
        }
      }
    }
  </script>
  <style>
    body { font-feature-settings: "cv02", "cv03", "cv04", "cv11"; }
    .custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
    .custom-scrollbar::-webkit-scrollbar-track { background: #0f172a; }
    .custom-scrollbar::-webkit-scrollbar-thumb { background: #334155; border-radius: 9999px; }
    .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #475569; }

    /* Modern Web Guidance: Native <dialog> Modal styling & scroll containment */
    dialog:modal {
      overscroll-behavior: contain;
      background: transparent;
      padding: 0;
      border: none;
      outline: none;
      max-width: 100vw;
      max-height: 100vh;
    }
    dialog::backdrop {
      overflow: hidden;
      overscroll-behavior: contain;
      background-color: rgba(9, 13, 22, 0.78);
      backdrop-filter: blur(6px);
      -webkit-backdrop-filter: blur(6px);
    }

    /* Modern Web Guidance: Responsive Table Sticky Header */
    .table-wrapper {
      overflow: auto;
      max-inline-size: 100%;
      container-type: inline-size;
    }
    .table-wrapper thead {
      position: sticky;
      inset-block-start: 0;
      z-index: 10;
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans selection:bg-brand-500 selection:text-slate-950">

  <!-- TOP HEADER -->
  <header class="border-b border-slate-800/80 bg-slate-900/80 backdrop-blur sticky top-0 z-40">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center">
        <span class="font-bold text-xl tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">TenderPulse</span>
      </div>

      <div class="flex items-center space-x-2.5">
        <button onclick="openCrawlModal()" class="inline-flex items-center space-x-2 bg-gradient-to-r from-brand-500 to-emerald-600 hover:from-brand-600 hover:to-emerald-700 text-slate-950 font-bold px-3.5 py-2 rounded-lg text-sm shadow-md shadow-brand-500/20 transition-all hover:scale-[1.02]">
          <i data-lucide="play" class="w-4 h-4 fill-slate-950"></i>
          <span>New Crawl</span>
        </button>
        <button onclick="exportData('csv')" class="inline-flex items-center space-x-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 rounded-lg text-xs font-semibold text-slate-200 transition">
          <i data-lucide="download" class="w-3.5 h-3.5"></i>
          <span>Export CSV</span>
        </button>
        <button onclick="exportData('jsonl')" class="inline-flex items-center space-x-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 rounded-lg text-xs font-semibold text-slate-200 transition">
          <i data-lucide="file-code" class="w-3.5 h-3.5"></i>
          <span>JSONL</span>
        </button>
        <button onclick="refreshAll()" title="Refresh Data" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-400 hover:text-white transition">
          <i data-lucide="refresh-cw" class="w-4 h-4"></i>
        </button>
      </div>
    </div>
  </header>

  <!-- MAIN CONTAINER -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 space-y-6 w-full">

    <!-- KPI STATS CARDS -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Total Tenders -->
      <div class="bg-slate-900/90 border border-slate-800/80 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Total Tenders</span>
          <span class="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <i data-lucide="layers" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-3 flex items-baseline space-x-2">
          <span id="stat-total-tenders" class="text-3xl font-extrabold tracking-tight text-white">-</span>
          <span class="text-xs text-brand-400 font-medium">durable keys</span>
        </div>
        <div class="mt-2 text-xs text-slate-400">Indexed in local SQLite store</div>
      </div>

      <!-- Total Value -->
      <div class="bg-slate-900/90 border border-slate-800/80 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Procurement Value</span>
          <span class="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <i data-lucide="indian-rupee" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-3 flex items-baseline space-x-2">
          <span id="stat-total-value" class="text-3xl font-extrabold tracking-tight text-white">-</span>
        </div>
        <div id="stat-avg-value" class="mt-2 text-xs text-slate-400">Avg Value: -</div>
      </div>

      <!-- Crawler Runs -->
      <div class="bg-slate-900/90 border border-slate-800/80 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Crawler Runs</span>
          <span class="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <i data-lucide="activity" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-3 flex items-baseline space-x-2">
          <span id="stat-total-runs" class="text-3xl font-extrabold tracking-tight text-white">-</span>
          <span id="stat-total-tasks" class="text-xs text-slate-400">(- tasks)</span>
        </div>
        <div class="mt-2 text-xs text-slate-400">State machine supervised</div>
      </div>

      <!-- Task Status / Health -->
      <div class="bg-slate-900/90 border border-slate-800/80 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Queue Health</span>
          <span class="p-2 rounded-xl bg-brand-500/10 text-brand-400 border border-brand-500/20">
            <i data-lucide="check-circle-2" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-3 flex items-center space-x-3 text-xs">
          <div class="flex items-center space-x-1.5">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
            <span id="stat-done-tasks" class="font-bold text-white">0</span>
            <span class="text-slate-400">Done</span>
          </div>
          <div class="flex items-center space-x-1.5">
            <span class="w-2.5 h-2.5 rounded-full bg-yellow-400"></span>
            <span id="stat-pending-tasks" class="font-bold text-white">0</span>
            <span class="text-slate-400">Pend</span>
          </div>
          <div class="flex items-center space-x-1.5">
            <span class="w-2.5 h-2.5 rounded-full bg-red-400"></span>
            <span id="stat-failed-tasks" class="font-bold text-white">0</span>
            <span class="text-slate-400">Fail</span>
          </div>
        </div>
        <div class="mt-3 w-full bg-slate-800 rounded-full h-1.5 overflow-hidden flex" id="task-progress-bar">
          <div class="bg-emerald-500 h-full w-full"></div>
        </div>
      </div>
    </div>

    <!-- TABS NAVIGATION -->
    <div class="border-b border-slate-800 flex items-center justify-between">
      <nav class="flex space-x-6 text-sm font-semibold">
        <button onclick="switchTab('tenders')" id="tab-btn-tenders" class="pb-3 border-b-2 border-brand-500 text-white flex items-center space-x-2">
          <i data-lucide="table" class="w-4 h-4 text-brand-400"></i>
          <span>Tenders Explorer</span>
        </button>
        <button onclick="switchTab('runs')" id="tab-btn-runs" class="pb-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center space-x-2">
          <i data-lucide="cpu" class="w-4 h-4"></i>
          <span>Runs & Queue State</span>
        </button>
        <button onclick="switchTab('analytics')" id="tab-btn-analytics" class="pb-3 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center space-x-2">
          <i data-lucide="pie-chart" class="w-4 h-4"></i>
          <span>Category Breakdown</span>
        </button>
      </nav>

      <div class="pb-3 flex items-center space-x-2">
        <span class="w-2 h-2 rounded-full bg-brand-500 animate-pulse"></span>
        <span class="text-xs text-slate-400 font-mono">SQLite WAL Active</span>
      </div>
    </div>

    <!-- TAB 1: TENDERS EXPLORER -->
    <section id="tab-content-tenders" class="space-y-4">
      <!-- Search & Filters Bar -->
      <div class="bg-slate-900/90 border border-slate-800 p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div class="flex-1 relative">
          <i data-lucide="search" class="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2"></i>
          <input type="text" id="search-input" onkeyup="handleSearchKey(event)" placeholder="Search by Tender ID, Title, Reference, or Department..." class="w-full bg-slate-950 border border-slate-700 rounded-lg pl-10 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand-500 transition placeholder:text-slate-500">
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <select id="filter-category" onchange="loadTenders(1)" class="bg-slate-950 border border-slate-700 text-xs text-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-500">
            <option value="all">All Categories</option>
            <option value="Works">Works</option>
            <option value="Goods">Goods</option>
            <option value="Services">Services</option>
            <option value="Consultancy">Consultancy</option>
          </select>
          <select id="sort-by" onchange="loadTenders(1)" class="bg-slate-950 border border-slate-700 text-xs text-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-500">
            <option value="created_at-desc">Newest First</option>
            <option value="tender_value-desc">Highest Value</option>
            <option value="tender_value-asc">Lowest Value</option>
            <option value="closing_date-asc">Closing Soonest</option>
          </select>
          <button onclick="loadTenders(1)" class="bg-slate-800 hover:bg-slate-700 px-3.5 py-2 rounded-lg text-xs font-semibold text-slate-200 border border-slate-700 transition">
            Filter
          </button>
        </div>
      </div>

      <!-- Tenders Table: Modern Web Responsive Table Region -->
      <div tabindex="0" role="region" aria-label="Tenders Directory" class="table-wrapper bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div class="overflow-x-auto custom-scrollbar">
          <table class="w-full text-left text-xs border-collapse">
            <thead>
              <tr class="bg-slate-950 border-b border-slate-800 text-slate-400 uppercase tracking-wider text-[11px] font-bold">
                <th class="py-3 px-4">Tender ID / Ref</th>
                <th class="py-3 px-4">Title & Scope</th>
                <th class="py-3 px-4">Organization / Chain</th>
                <th class="py-3 px-4">Category</th>
                <th class="py-3 px-4 text-right">Tender Value</th>
                <th class="py-3 px-4">Closing Date</th>
                <th class="py-3 px-4 text-center">Action</th>
              </tr>
            </thead>
            <tbody id="tenders-tbody" class="divide-y divide-slate-800 text-slate-300">
              <tr>
                <td colspan="7" class="py-12 text-center text-slate-500">
                  <div class="inline-flex items-center space-x-2">
                    <i data-lucide="loader" class="w-5 h-5 animate-spin text-brand-500"></i>
                    <span>Loading tenders database...</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination Bar -->
        <div class="border-t border-slate-800 px-4 py-3 bg-slate-950/70 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-400 gap-2">
          <div>
            Showing <span id="pag-start" class="font-semibold text-slate-200">1</span> to <span id="pag-end" class="font-semibold text-slate-200">15</span> of <span id="pag-total" class="font-semibold text-slate-200">0</span> records
          </div>
          <div class="flex items-center space-x-1.5">
            <button id="pag-prev" onclick="changePage(-1)" class="px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed">
              Prev
            </button>
            <span id="pag-current" class="px-3 py-1 font-mono text-slate-200">1 / 1</span>
            <button id="pag-next" onclick="changePage(1)" class="px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed">
              Next
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- TAB 2: RUNS & QUEUE STATE -->
    <section id="tab-content-runs" class="space-y-4 hidden">
      <div tabindex="0" role="region" aria-label="Crawl Runs Table" class="table-wrapper bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div class="p-4 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h2 class="text-sm font-bold text-white">Crawl Execution Runs</h2>
            <p class="text-xs text-slate-400">Supervised runs tracked in SQLite queue engine with heartbeat and retry classification</p>
          </div>
          <button onclick="loadRuns()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700 transition flex items-center space-x-1">
            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
            <span>Refresh Runs</span>
          </button>
        </div>
        <div class="overflow-x-auto custom-scrollbar">
          <table class="w-full text-left text-xs border-collapse">
            <thead>
              <tr class="bg-slate-950 border-b border-slate-800 text-slate-400 uppercase tracking-wider text-[11px] font-bold">
                <th class="py-3 px-4">Run ID</th>
                <th class="py-3 px-4">Status</th>
                <th class="py-3 px-4">Started At</th>
                <th class="py-3 px-4 text-center">Total Tasks</th>
                <th class="py-3 px-4 text-center">Done</th>
                <th class="py-3 px-4 text-center">Pending</th>
                <th class="py-3 px-4 text-center">Failed</th>
                <th class="py-3 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody id="runs-tbody" class="divide-y divide-slate-800 text-slate-300">
              <tr>
                <td colspan="8" class="py-8 text-center text-slate-500">Loading runs...</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Task Details Drawer / Section -->
      <div id="tasks-drawer" class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 hidden space-y-3">
        <div class="flex items-center justify-between">
          <h3 class="text-xs font-bold text-white uppercase tracking-wider flex items-center space-x-2">
            <i data-lucide="list-tree" class="w-4 h-4 text-brand-400"></i>
            <span>Task Queue Breakdown: <span id="drawer-run-id" class="font-mono text-brand-400">-</span></span>
          </h3>
          <button onclick="closeTasksDrawer()" class="text-xs text-slate-400 hover:text-white">&times; Close</button>
        </div>
        <div class="overflow-x-auto custom-scrollbar">
          <table class="w-full text-left text-xs border-collapse">
            <thead>
              <tr class="bg-slate-950 text-slate-400 uppercase text-[10px]">
                <th class="py-2 px-3">Task ID</th>
                <th class="py-2 px-3">Type</th>
                <th class="py-2 px-3">Status</th>
                <th class="py-2 px-3">Attempt</th>
                <th class="py-2 px-3">Heartbeat</th>
                <th class="py-2 px-3">Error Class</th>
              </tr>
            </thead>
            <tbody id="tasks-tbody" class="divide-y divide-slate-800">
              <!-- Dynamically populated -->
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- TAB 3: CATEGORY & ORG BREAKDOWN -->
    <section id="tab-content-analytics" class="space-y-4 hidden">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Category Distribution -->
        <div class="bg-slate-900/90 border border-slate-800 p-5 rounded-xl">
          <h3 class="text-sm font-bold text-white mb-1">Category Distribution</h3>
          <p class="text-xs text-slate-400 mb-4">Volume of tenders grouped by primary procurement type</p>
          <div id="category-bars" class="space-y-3">
            <!-- Dynamically populated -->
          </div>
        </div>

        <!-- Top Organizations -->
        <div class="bg-slate-900/90 border border-slate-800 p-5 rounded-xl">
          <h3 class="text-sm font-bold text-white mb-1">Top Procurement Entities</h3>
          <p class="text-xs text-slate-400 mb-4">Ministries and departments with highest active listings</p>
          <div id="org-bars" class="space-y-3">
            <!-- Dynamically populated -->
          </div>
        </div>
      </div>
    </section>

  </main>

  <!-- NATIVE MODAL: TENDER DETAIL (Modern Web Guidance: <dialog closedby="any">) -->
  <dialog id="tender-modal" closedby="any" aria-labelledby="modal-title">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden m-auto">
      <div class="p-5 border-b border-slate-800 flex items-start justify-between bg-slate-950/70">
        <div>
          <div class="flex items-center space-x-2">
            <span id="modal-tid" class="font-mono text-xs font-bold px-2 py-0.5 rounded bg-brand-500/20 text-brand-400 border border-brand-500/30">-</span>
            <span id="modal-ref" class="text-xs text-slate-400 font-mono">-</span>
          </div>
          <h3 id="modal-title" class="text-base font-bold text-white mt-1 leading-snug">-</h3>
        </div>
        <button type="button" onclick="closeTenderModal()" aria-label="Close modal" class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition">
          <i data-lucide="x" class="w-5 h-5"></i>
        </button>
      </div>

      <div class="p-6 overflow-y-auto custom-scrollbar space-y-4 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl">
            <span class="text-slate-500 block mb-1 uppercase font-semibold">Tender Value</span>
            <span id="modal-value" class="text-base font-bold text-white font-mono">-</span>
          </div>
          <div class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl">
            <span class="text-slate-500 block mb-1 uppercase font-semibold">EMD Amount</span>
            <span id="modal-emd" class="text-base font-bold text-slate-300 font-mono">-</span>
          </div>
        </div>

        <div class="space-y-1.5">
          <span class="text-slate-400 uppercase font-semibold text-[11px] block">Organization Chain</span>
          <div id="modal-org" class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl text-slate-300 font-medium">-</div>
        </div>

        <div class="grid grid-cols-3 gap-2">
          <div class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl">
            <span class="text-slate-500 block text-[10px] uppercase font-semibold">Published Date</span>
            <span id="modal-pubdate" class="text-slate-200 font-medium">-</span>
          </div>
          <div class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl">
            <span class="text-slate-500 block text-[10px] uppercase font-semibold">Closing Date</span>
            <span id="modal-clsdate" class="text-amber-400 font-medium">-</span>
          </div>
          <div class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl">
            <span class="text-slate-500 block text-[10px] uppercase font-semibold">Tender Category</span>
            <span id="modal-category" class="text-slate-200 font-medium">-</span>
          </div>
        </div>

        <div>
          <span class="text-slate-400 uppercase font-semibold text-[11px] block mb-1">Official Portal Detail Link</span>
          <div id="modal-url-container" class="break-all font-mono text-[11px] text-slate-400 bg-slate-950 p-2.5 rounded-lg border border-slate-800">
            -
          </div>
        </div>
      </div>

      <div class="p-4 border-t border-slate-800 bg-slate-950/70 flex justify-end">
        <button type="button" onclick="closeTenderModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg transition">
          Close
        </button>
      </div>
    </div>
  </dialog>

  <!-- NATIVE MODAL: NEW CRAWL (Modern Web Guidance: <dialog closedby="any">) -->
  <dialog id="crawl-modal" closedby="any" aria-labelledby="crawl-modal-title">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full shadow-2xl overflow-hidden m-auto">
      <div class="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/70">
        <h3 id="crawl-modal-title" class="text-sm font-bold text-white flex items-center space-x-2">
          <i data-lucide="play" class="w-4 h-4 text-brand-400"></i>
          <span>Trigger New Crawl Run</span>
        </h3>
        <button type="button" onclick="closeCrawlModal()" aria-label="Close modal" class="text-slate-400 hover:text-white transition">
          <i data-lucide="x" class="w-4 h-4"></i>
        </button>
      </div>

      <form id="crawl-form" onsubmit="submitCrawl(event)" class="p-5 space-y-3.5 text-xs">
        <div>
          <label for="crawl-date-from" class="block text-slate-400 font-medium mb-1">Date From</label>
          <input type="date" id="crawl-date-from" value="2026-04-01" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-brand-500">
        </div>
        <div>
          <label for="crawl-date-to" class="block text-slate-400 font-medium mb-1">Date To</label>
          <input type="date" id="crawl-date-to" value="2026-05-05" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-brand-500">
        </div>
        <div>
          <label for="crawl-pages" class="block text-slate-400 font-medium mb-1">Pages Limit (Atomic Tasks)</label>
          <input type="number" id="crawl-pages" min="1" max="50" value="5" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-brand-500">
        </div>
        <div>
          <label for="crawl-mode" class="block text-slate-400 font-medium mb-1">Engine Mode</label>
          <select id="crawl-mode" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-brand-500">
            <option value="mock">Mock Engine (Fast local state transition)</option>
            <option value="smoke">Live Smoke (Direct Playwright)</option>
          </select>
        </div>

        <div class="pt-2 flex justify-end space-x-2">
          <button type="button" onclick="closeCrawlModal()" class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg font-semibold transition">Cancel</button>
          <button type="submit" id="btn-submit-crawl" class="px-4 py-2 bg-brand-500 hover:bg-brand-600 text-slate-950 font-bold rounded-lg transition shadow-md shadow-brand-500/20">Launch Crawl</button>
        </div>
      </form>
    </div>
  </dialog>

  <!-- ACCESSIBLE TOAST NOTIFICATIONS (Modern Web Guidance: region + live region) -->
  <div role="region" aria-label="Notifications" id="notification-region" class="fixed bottom-5 right-5 z-50 flex flex-col space-y-2 pointer-events-none">
    <div id="notification-live" aria-live="polite" class="sr-only"></div>
    <div id="toast" class="pointer-events-auto bg-slate-900 border border-slate-700 px-4 py-3 rounded-xl shadow-2xl flex items-center space-x-3 text-xs text-slate-200 hidden transition-all duration-300">
      <i data-lucide="info" class="w-4 h-4 text-brand-400"></i>
      <span id="toast-msg">Action performed</span>
      <button type="button" onclick="document.getElementById('toast').classList.add('hidden')" aria-label="Dismiss toast" class="text-slate-400 hover:text-white ml-2">
        <i data-lucide="x" class="w-3.5 h-3.5"></i>
      </button>
    </div>
  </div>

  <!-- JAVASCRIPT LOGIC -->
  <script>
    let currentPage = 1;
    let totalPages = 1;

    // Modern Web Guidance: Native Dialog Light-Dismiss Fallback
    function setupDialogFallbacks() {
      if (!('closedBy' in HTMLDialogElement.prototype)) {
        document.querySelectorAll('dialog[closedby="any"]').forEach(dialog => {
          let pressedOutside = false;
          const outside = (e, d) => {
            const r = d.getBoundingClientRect();
            return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
          };
          dialog.addEventListener('pointerdown', (e) => { pressedOutside = outside(e, dialog); });
          dialog.addEventListener('pointerup', (e) => {
            if (pressedOutside && outside(e, dialog)) dialog.close();
          });
        });
      }
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      const live = document.getElementById('notification-live');
      document.getElementById('toast-msg').innerText = msg;
      if (live) live.textContent = msg;
      toast.classList.remove('hidden');
      setTimeout(() => { toast.classList.add('hidden'); }, 3500);
      lucide.createIcons();
    }

    function formatINR(val) {
      if (val === null || val === undefined || isNaN(val)) return 'N/A';
      const num = Number(val);
      if (num >= 10000000) {
        return '₹ ' + (num / 10000000).toFixed(2) + ' Cr';
      } else if (num >= 100000) {
        return '₹ ' + (num / 100000).toFixed(2) + ' Lakh';
      }
      return '₹ ' + num.toLocaleString('en-IN');
    }

    async function loadStats() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        document.getElementById('stat-total-tenders').innerText = data.total_tenders.toLocaleString('en-IN');
        document.getElementById('stat-total-value').innerText = formatINR(data.total_value);
        document.getElementById('stat-avg-value').innerText = 'Avg Value: ' + formatINR(data.avg_value);
        document.getElementById('stat-total-runs').innerText = data.total_runs;
        document.getElementById('stat-total-tasks').innerText = '(' + data.total_tasks + ' tasks)';

        const done = data.task_status.DONE || 0;
        const pending = data.task_status.PENDING || 0;
        const failed = (data.task_status.FAILED_RETRYABLE || 0) + (data.task_status.FAILED_PERMANENT || 0);

        document.getElementById('stat-done-tasks').innerText = done;
        document.getElementById('stat-pending-tasks').innerText = pending;
        document.getElementById('stat-failed-tasks').innerText = failed;

        // Progress bar
        const total = (done + pending + failed) || 1;
        const donePct = (done / total) * 100;
        document.getElementById('task-progress-bar').innerHTML = `
          <div style="width: ${donePct}%" class="bg-emerald-500 h-full"></div>
          <div style="width: ${(pending/total)*100}%" class="bg-yellow-400 h-full"></div>
          <div style="width: ${(failed/total)*100}%" class="bg-red-500 h-full"></div>
        `;

        // Render analytics bars
        const catBox = document.getElementById('category-bars');
        catBox.innerHTML = '';
        data.category_distribution.forEach(c => {
          const pct = Math.min(100, (c.count / (data.total_tenders || 1)) * 100).toFixed(1);
          catBox.innerHTML += `
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span class="font-medium text-slate-300">${c.category}</span>
                <span class="text-slate-400">${c.count} (${pct}%)</span>
              </div>
              <div class="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
                <div class="bg-brand-500 h-full rounded-full" style="width: ${pct}%"></div>
              </div>
            </div>
          `;
        });

        const orgBox = document.getElementById('org-bars');
        orgBox.innerHTML = '';
        data.top_organizations.forEach(o => {
          const cleanOrg = o.org.length > 50 ? o.org.substring(0, 48) + '...' : o.org;
          orgBox.innerHTML += `
            <div class="p-2.5 bg-slate-950/70 border border-slate-800 rounded-lg flex items-center justify-between text-xs">
              <span class="text-slate-300 font-medium truncate mr-2" title="${o.org}">${cleanOrg}</span>
              <span class="px-2 py-0.5 rounded bg-brand-500/10 text-brand-400 font-bold border border-brand-500/20">${o.count}</span>
            </div>
          `;
        });

      } catch (err) {
        console.error('Stats error:', err);
      }
    }

    async function loadTenders(page = 1) {
      currentPage = page;
      const q = document.getElementById('search-input').value;
      const cat = document.getElementById('filter-category').value;
      const [sortBy, sortOrder] = document.getElementById('sort-by').value.split('-');

      const tbody = document.getElementById('tenders-tbody');
      tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-slate-500"><i data-lucide="loader" class="w-5 h-5 animate-spin mx-auto text-brand-500 mb-2"></i>Loading tenders...</td></tr>`;
      lucide.createIcons();

      try {
        let url = `/api/tenders?page=${page}&page_size=15&sort_by=${sortBy}&sort_order=${sortOrder}`;
        if (q) url += `&q=${encodeURIComponent(q)}`;
        if (cat && cat !== 'all') url += `&category=${encodeURIComponent(cat)}`;

        const res = await fetch(url);
        const data = await res.json();

        totalPages = data.pages || 1;
        document.getElementById('pag-total').innerText = data.total;
        document.getElementById('pag-start').innerText = data.total > 0 ? (data.page - 1) * data.page_size + 1 : 0;
        document.getElementById('pag-end').innerText = Math.min(data.page * data.page_size, data.total);
        document.getElementById('pag-current').innerText = `${data.page} / ${totalPages}`;
        document.getElementById('pag-prev').disabled = data.page <= 1;
        document.getElementById('pag-next').disabled = data.page >= totalPages;

        if (!data.items || data.items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-slate-500">No matching tenders found.</td></tr>`;
          return;
        }

        tbody.innerHTML = '';
        data.items.forEach(t => {
          const valFormatted = formatINR(t.tender_value);
          const closeDate = t.closing_date ? t.closing_date.substring(0, 10) : 'Open';
          const orgChain = t.org_chain || 'General Public Entity';
          const displayOrg = orgChain.length > 35 ? orgChain.substring(0, 32) + '...' : orgChain;
          const ref = t.reference_number || 'N/A';

          tbody.innerHTML += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-3 px-4 font-mono font-medium text-slate-200">
                <div class="text-brand-400 font-bold">${t.tender_id}</div>
                <div class="text-[10px] text-slate-500">${ref}</div>
              </td>
              <td class="py-3 px-4 max-w-xs">
                <div class="font-medium text-slate-200 truncate" title="${t.title || 'Untitled'}">${t.title || 'Untitled'}</div>
                <div class="text-[10px] text-slate-500">${t.tender_type || 'Open'}</div>
              </td>
              <td class="py-3 px-4 text-slate-400 max-w-[200px] truncate" title="${orgChain}">
                ${displayOrg}
              </td>
              <td class="py-3 px-4">
                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">${t.category || 'Works'}</span>
              </td>
              <td class="py-3 px-4 text-right font-mono font-bold text-slate-200">
                ${valFormatted}
              </td>
              <td class="py-3 px-4 font-mono text-slate-400">
                ${closeDate}
              </td>
              <td class="py-3 px-4 text-center">
                <button type="button" onclick="viewTender('${t.tender_id}')" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-brand-400 hover:text-brand-300 border border-slate-700 font-semibold transition">
                  Details
                </button>
              </td>
            </tr>
          `;
        });
        lucide.createIcons();

      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-red-400">Error loading tenders: ${err.message}</td></tr>`;
      }
    }

    async function viewTender(id) {
      try {
        const res = await fetch(`/api/tenders/${id}`);
        const t = await res.json();

        document.getElementById('modal-tid').innerText = t.tender_id;
        document.getElementById('modal-ref').innerText = t.reference_number || 'N/A';
        document.getElementById('modal-title').innerText = t.title || 'Untitled Tender';
        document.getElementById('modal-value').innerText = formatINR(t.tender_value);
        document.getElementById('modal-emd').innerText = formatINR(t.emd_amount);
        document.getElementById('modal-org').innerText = t.org_chain || 'General Public Sector';
        document.getElementById('modal-pubdate').innerText = t.published_date || 'N/A';
        document.getElementById('modal-clsdate').innerText = t.closing_date || 'N/A';
        document.getElementById('modal-category').innerText = t.category || 'Works';

        const urlBox = document.getElementById('modal-url-container');
        if (t.detail_url) {
          urlBox.innerHTML = `<a href="${t.detail_url}" target="_blank" rel="noopener noreferrer" class="text-brand-400 hover:underline flex items-center space-x-1"><span>${t.detail_url}</span> <i data-lucide="external-link" class="w-3 h-3 inline"></i></a>`;
        } else {
          urlBox.innerText = 'No direct portal session link available';
        }

        const modal = document.getElementById('tender-modal');
        modal.showModal();
        lucide.createIcons();
      } catch (err) {
        showToast('Error loading details: ' + err.message);
      }
    }

    function closeTenderModal() {
      document.getElementById('tender-modal').close();
    }

    async function loadRuns() {
      const tbody = document.getElementById('runs-tbody');
      tbody.innerHTML = `<tr><td colspan="8" class="py-6 text-center text-slate-500">Loading runs...</td></tr>`;

      try {
        const res = await fetch('/api/runs');
        const runs = await res.json();

        if (!runs || runs.length === 0) {
          tbody.innerHTML = `<tr><td colspan="8" class="py-6 text-center text-slate-500">No crawl runs recorded.</td></tr>`;
          return;
        }

        tbody.innerHTML = '';
        runs.forEach(r => {
          let statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300">UNKNOWN</span>';
          if (r.status === 'running') {
            statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-400 border border-blue-500/30 flex items-center space-x-1 w-max"><span class="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping mr-1"></span>RUNNING</span>';
          } else if (r.status === 'completed' || r.tasks_pending === 0) {
            statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">COMPLETED</span>';
          }

          tbody.innerHTML += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-3 px-4 font-mono font-bold text-slate-200">${r.id.substring(0, 8)}...</td>
              <td class="py-3 px-4">${statusBadge}</td>
              <td class="py-3 px-4 text-slate-400 font-mono">${r.created_at.substring(0, 19).replace('T', ' ')}</td>
              <td class="py-3 px-4 text-center font-bold text-white">${r.tasks_total}</td>
              <td class="py-3 px-4 text-center text-emerald-400 font-semibold">${r.tasks_done}</td>
              <td class="py-3 px-4 text-center text-yellow-400 font-semibold">${r.tasks_pending}</td>
              <td class="py-3 px-4 text-center text-red-400 font-semibold">${r.tasks_failed}</td>
              <td class="py-3 px-4 text-right">
                <button type="button" onclick="viewRunTasks('${r.id}')" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition">Tasks</button>
              </td>
            </tr>
          `;
        });
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="py-6 text-center text-red-400">Error loading runs: ${err.message}</td></tr>`;
      }
    }

    async function viewRunTasks(runId) {
      document.getElementById('tasks-drawer').classList.remove('hidden');
      document.getElementById('drawer-run-id').innerText = runId;
      const tbody = document.getElementById('tasks-tbody');
      tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-slate-500">Loading tasks for run...</td></tr>`;

      try {
        const res = await fetch(`/api/runs/${runId}/tasks`);
        const tasks = await res.json();
        tbody.innerHTML = '';
        tasks.forEach(t => {
          let badge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-800 text-slate-300">${t.status}</span>`;
          if (t.status === 'DONE') badge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-400">DONE</span>`;
          if (t.status === 'RUNNING') badge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-500/20 text-blue-400">RUNNING</span>`;
          if (t.status.includes('FAIL')) badge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-red-500/20 text-red-400">${t.status}</span>`;

          tbody.innerHTML += `
            <tr class="hover:bg-slate-800/20 font-mono text-[11px]">
              <td class="py-2 px-3 text-slate-400">${t.id.substring(0, 8)}...</td>
              <td class="py-2 px-3 text-slate-300">${t.task_type}</td>
              <td class="py-2 px-3">${badge}</td>
              <td class="py-2 px-3 text-slate-300">${t.attempt_count} / ${t.max_attempts}</td>
              <td class="py-2 px-3 text-slate-500">${t.heartbeat_at ? t.heartbeat_at.substring(11, 19) : '-'}</td>
              <td class="py-2 px-3 text-slate-400">${t.error_class || '-'}</td>
            </tr>
          `;
        });
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-red-400">Failed to load tasks</td></tr>`;
      }
    }

    function closeTasksDrawer() {
      document.getElementById('tasks-drawer').classList.add('hidden');
    }

    function switchTab(tab) {
      ['tenders', 'runs', 'analytics'].forEach(t => {
        document.getElementById(`tab-content-${t}`).classList.add('hidden');
        const btn = document.getElementById(`tab-btn-${t}`);
        btn.classList.remove('border-brand-500', 'text-white');
        btn.classList.add('border-transparent', 'text-slate-400');
      });

      document.getElementById(`tab-content-${tab}`).classList.remove('hidden');
      const activeBtn = document.getElementById(`tab-btn-${tab}`);
      activeBtn.classList.add('border-brand-500', 'text-white');
      activeBtn.classList.remove('border-transparent', 'text-slate-400');

      if (tab === 'runs') loadRuns();
      if (tab === 'tenders') loadTenders(currentPage);
      if (tab === 'analytics') loadStats();
      lucide.createIcons();
    }

    function handleSearchKey(e) {
      if (e.key === 'Enter') {
        loadTenders(1);
      }
    }

    function changePage(delta) {
      const target = currentPage + delta;
      if (target >= 1 && target <= totalPages) {
        loadTenders(target);
      }
    }

    function openCrawlModal() {
      document.getElementById('crawl-modal').showModal();
    }

    function closeCrawlModal() {
      document.getElementById('crawl-modal').close();
    }

    async function submitCrawl(e) {
      e.preventDefault();
      const btn = document.getElementById('btn-submit-crawl');
      btn.disabled = true;
      btn.innerText = 'Starting...';

      const payload = {
        date_from: document.getElementById('crawl-date-from').value,
        date_to: document.getElementById('crawl-date-to').value,
        pages_limit: parseInt(document.getElementById('crawl-pages').value, 10),
        mode: document.getElementById('crawl-mode').value
      };

      try {
        const res = await fetch('/api/crawl', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        showToast(data.message || 'Crawl started!');
        closeCrawlModal();
        refreshAll();
      } catch (err) {
        showToast('Failed to start crawl: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerText = 'Launch Crawl';
      }
    }

    function exportData(fmt) {
      showToast(`Generating ${fmt.toUpperCase()} export...`);
      window.location.href = `/api/export?format=${fmt}`;
    }

    function refreshAll() {
      loadStats();
      loadTenders(currentPage);
      loadRuns();
      showToast('Dashboard refreshed');
    }

    // Auto-init
    window.addEventListener('DOMContentLoaded', () => {
      lucide.createIcons();
      setupDialogFallbacks();
      loadStats();
      loadTenders(1);
    });
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tender_royal_pulse.web.app:create_app", host="127.0.0.1", port=8000, reload=True, factory=True)
