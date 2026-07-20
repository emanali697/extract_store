# AGENTS.md — Store Extractor

This file is a living reference for AI coding agents working on the **Store Extractor** project. Read it first before making changes.

---

## Project overview

Store Extractor is a desktop-style web application that processes dashcam videos and extracts structured store/merchant data (name, phone, category, location, status, etc.).

The workflow is:

1. User uploads a video through the React frontend.
2. The FastAPI backend saves the file and spawns an external Python ML pipeline.
3. The pipeline extracts frames, reads GPS/speed overlays, runs OCR and Gemini analysis, matches stores with Google Places, and determines operating status.
4. Results stream back to the browser in real time over WebSocket.
5. The user reviews uncertain stores, then pushes approved data to Firebase / traders-data-live or exports CSV/Excel.

The project is **Arabic-first**: the UI is RTL, labels and status values are in Arabic, and CSV exports include a UTF-8 BOM for Excel compatibility.

The repo is split into three parts:

```text
extract stores/          # this repo
├── backend/             # FastAPI orchestrator + persistence
├── frontend/            # React + Vite + Bootstrap RTL UI
└── ../pipeline/         # external ML pipeline (not in this repo, but required)
```

---

## Technology stack

### Backend (`backend/`)

| Layer | Technology |
|---|---|
| Framework | FastAPI (Python 3.12) |
| Server | Uvicorn (`uvicorn[standard]`) |
| Validation | Pydantic v2 |
| Real-time | FastAPI WebSockets (`/ws/progress/{job_id}`) |
| Persistence | SQLite (`backend/state.db`) |
| Cloud | Firebase Admin SDK (`firebase-admin`) |
| File uploads | `python-multipart` |

### Frontend (`frontend/`)

| Layer | Technology |
|---|---|
| Framework | React 19 (functional components + hooks) |
| Build tool | Vite 8 |
| Routing | React Router DOM v7 |
| State | Zustand 5 with `persist` middleware (localStorage) |
| HTTP client | Axios |
| UI | Bootstrap 5.3 RTL + React-Bootstrap |
| Icons | Bootstrap Icons (`<i className="bi bi-...">`) |
| Client Firebase | Firebase JS SDK (optional init only) |

### External pipeline (`../pipeline/`)

The backend shells out to a separate Python pipeline that lives outside this repo folder. It is discovered by walking up to 4 parent directories from `backend/` until `pipeline/main.py` is found. Key scripts the backend expects:

- `pipeline/main.py` — v3 raw extraction → `stores_raw.json`
- `pipeline/main_v5.py` — Google candidate matching → `stores_v5_raw.json`
- `pipeline/run_v6.py` — status check + auto-review + Excel → `stores_v6_final.json`

The pipeline communicates progress via stdout markers such as `--- STAGE N: ...` and `__PROGRESS__ current=X total=Y`.

---

## Directory structure

```text
backend/
├── app.py                      # FastAPI app and all REST/WebSocket routes
├── config.py                   # Paths, CORS, Firebase key locations
├── db.py                       # SQLite persistence layer
├── jobs.py                     # Job dataclass + in-memory JobManager + pub/sub
├── runner.py                   # Subprocess orchestrator for the pipeline
├── stages.py                   # Maps pipeline stdout to UI stage indices
├── firebase_service.py         # Firebase Admin SDK wrapper (store-extract project)
├── traders_firebase_service.py # Adapter for traders-data-live Firestore project
├── requirements.txt
├── state.db                    # created at runtime
├── uploads/                    # uploaded videos
├── jobs/                       # per-job pipeline outputs
├── firebase_key.json           # service-account key (store-extract)
├── newdb_key.json              # service-account key
├── traders_data_live_key.json  # service-account key (traders-data-live)
└── _*.py                       # one-off utilities and batch/repair scripts

frontend/
├── index.html                  # RTL Arabic entry, loads Cairo font
├── vite.config.js              # minimal Vite + React config
├── eslint.config.js            # flat ESLint config
├── package.json
├── .env.development            # VITE_API_BASE_URL and Firebase web config
└── src/
    ├── main.jsx                # app bootstrap
    ├── App.jsx                 # top-level routes
    ├── index.css               # global styles + Bootstrap overrides
    ├── components/
    │   ├── Layout.jsx          # shell with nav and sidebar
    │   ├── Sidebar.jsx         # analysis settings form
    │   ├── StageList.jsx       # pipeline stage list
    │   └── ResumeBanner.jsx    # resume previous backend jobs
    ├── pages/
    │   ├── UploadPage.jsx
    │   ├── ProgressPage.jsx
    │   ├── ReviewPage.jsx
    │   └── ResultsPage.jsx
    ├── services/
    │   ├── api.js              # Axios backend client + WebSocket helper
    │   ├── firebase.js         # optional Firebase client init
    │   └── mockRunner.js       # local mock analysis runner
    ├── store/
    │   └── appStore.js         # Zustand global state
    └── data/
        ├── stages.js           # 9 UI pipeline stage definitions
        └── demoData.js         # demo summary/stores/review items
```

---

## Build and run commands

### Backend

```powershell
cd "d:/sharea elnassim/extract stores/backend"
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

API docs are available at `http://localhost:8000/docs`.

### Frontend

```powershell
cd "d:/sharea elnassim/extract stores/frontend"
npm install
npm run dev      # Vite dev server on http://localhost:5173
```

Other frontend scripts:

```powershell
npm run build    # production build → dist/
npm run preview  # preview production build
npm run lint     # run ESLint
```

### Batch processing

```powershell
cd backend
python _batch_run.py   # backend must already be running on :8000
```

### Data push utilities

```powershell
cd backend
python push_all_to_newdb.py <job_id> ... [--collection stores_dashcam] [--dry-run]
```

---

## Runtime architecture

### Job lifecycle

A job passes through these states:

```text
queued → running → done | error | interrupted
```

- `interrupted` is assigned to jobs that were `running` when the backend shut down and are reloaded from SQLite on startup.
- `JobManager` keeps all jobs in memory and persists them to SQLite via `db.upsert_job()`.
- WebSocket subscribers receive `status`, `stage`, `log`, and `results` events.

### Pipeline orchestration

1. `POST /jobs` creates a `Job` and immediately returns `{jobId, status}`.
2. `asyncio.create_task(run_pipeline(job))` launches `runner.py`.
3. `runner.py` spawns the pipeline as a subprocess and reads stdout line-by-line.
4. Stage markers update `job.stages[ui_idx]`; progress hints update `current/total`.
5. When the process finishes, `runner.py` reads the most complete JSON available (`v6 > v5 > v3`) and shapes it into UI results.
6. Results are persisted and emitted over WebSocket.

### REST endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API info + Firebase status |
| `GET` | `/health` | Firebase + traders Firebase readiness |
| `POST` | `/upload` | Upload video → `backend/uploads/` |
| `POST` | `/jobs` | Create job from settings and start pipeline |
| `GET` | `/jobs` | List recent jobs (newest first) — used for auto-resume |
| `GET` | `/jobs/{job_id}` | Job status + stages snapshot |
| `GET` | `/jobs/{job_id}/sign/{filename}` | Serve sign crop image for review UI |
| `GET` | `/jobs/{job_id}/results` | Final processed results |
| `GET` | `/jobs/{job_id}/review` | Items flagged for human review |
| `POST` | `/jobs/{job_id}/approve` | Push approved stores to default Firebase project |
| `POST` | `/jobs/{job_id}/traders/preview` | Dry-run mapping to traders-data-live schema |
| `POST` | `/jobs/{job_id}/traders/push` | Write to traders-data-live Firestore |
| `GET` | `/jobs/{job_id}/export.csv` | CSV export (UTF-8 with BOM for Excel) |
| `GET` | `/jobs/{job_id}/excel` | Download produced Excel (prefers v6 > v5 > v3) |
| `DELETE` | `/jobs/{job_id}/video` | Delete source video file |
| `WS` | `/ws/progress/{job_id}` | Live progress stream |

### Frontend routes

| Path | Page |
|---|---|
| `/` | redirect → `/upload` |
| `/upload` | Upload + configure analysis |
| `/progress` | Live pipeline progress |
| `/review` | Human review queue |
| `/results` | Results table, exports, Firebase/traders push |

---

## Configuration

### Backend

Configuration lives in `backend/config.py` and can be overridden via environment variables loaded from `backend/.env` (using `python-dotenv`). See `backend/.env.example` for the available variables.

Important values:

- `UPLOAD_DIR` — default `backend/uploads/` (override with `UPLOAD_DIR`)
- `JOBS_DIR` — default `backend/jobs/` (override with `JOBS_DIR`)
- `PIPELINE_DIR` — discovered by walking up to 4 parents looking for `pipeline/main.py`, unless `PIPELINE_DIR` is set
- `FIREBASE_KEY_PATH` — default `backend/firebase_key.json` (override with `FIREBASE_KEY_PATH`)
- `FIRESTORE_COLLECTION` — default `"stores"` (override with `FIRESTORE_COLLECTION`)
- `ALLOWED_ORIGINS` — default Vite dev ports (override with comma-separated `ALLOWED_ORIGINS`)

Service-account keys and `.env` are gitignored and must be supplied outside the repository.

### Frontend

Environment variables in `frontend/.env.development`:

```text
VITE_API_BASE_URL=http://localhost:8000
```

Optional Firebase web config (only used for client-side init):

```text
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=...
VITE_FIREBASE_STORAGE_BUCKET=...
VITE_FIREBASE_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
```

---

## Code style guidelines

### Python (backend)

- Use `from __future__ import annotations` at the top of modules.
- Type hints are encouraged; use `str | None` style (Python 3.10+).
- Asyncio-based; on Windows the app sets `WindowsProactorEventLoopPolicy` so `create_subprocess_exec` works.
- Reconfigure stdout for UTF-8 in CLI scripts: `sys.stdout.reconfigure(encoding="utf-8")`.
- Keep modules flat — the backend does not use routers or blueprints.
- Fire-and-forget pipeline tasks with `asyncio.create_task`.
- Persistence failures must never crash the pipeline (see `JobManager.persist`).

### JavaScript / React (frontend)

- No semicolons, single quotes, 2-space indentation.
- Functional components as default exports.
- Use Zustand for global state; keep local UI state with hooks.
- Bootstrap Icons via `<i className="bi bi-icon-name">`.
- RTL-aware classes: `.num-ltr` keeps digits/English LTR inside Arabic text.
- API calls live in `services/api.js`; do not call Axios directly from pages.

---

## Testing instructions

There are **no automated tests** in this project.

- No `tests/` directories.
- No `pytest.ini`, `tox.ini`, Jest, Vitest, or CI configuration.

Manual validation flow:

1. Start the backend on `:8000`.
2. Start the frontend on `:5173`.
3. Upload a sample video and create a job.
4. Confirm WebSocket progress events arrive in the browser console/network tab.
5. Verify `backend/jobs/{job_id}/` contains expected JSON and Excel outputs.
6. Check `http://localhost:8000/health` reports Firebase statuses.

---

## Security considerations

- **Service-account JSON keys are stored directly in `backend/`**: `firebase_key.json`, `newdb_key.json`, `traders_data_live_key.json`. Do not commit these to version control.
- The backend does not use environment variables for secrets or config; credentials are file-based.
- CORS allows `localhost:5173` only.
- Upload endpoint accepts arbitrary files but stores them under `backend/uploads/` with the original filename sanitized by `Path(filename).name`.
- Sign image endpoint restricts filenames to `sign_*.jpg`.
- SQLite is single-writer; do not run multiple uvicorn workers against the same `state.db`.

---

## Project-specific conventions

1. **Flat backend structure** — all routes live in `app.py`; there are no routers or blueprints.
2. **Pipeline subprocess model** — the backend is a thin orchestrator around `../pipeline/`.
3. **Stage mapping** — pipeline `--- STAGE N: ...` markers map to the 9 UI stages defined in `frontend/src/data/stages.js`. Stage 7 (auto-detect center) has no UI row and is folded into stage 6 (Places).
4. **v3/v5/v6 fallback chain** — `runner.py` and `_read_results()` prefer `stores_v6_final.json`, then `stores_v5_raw.json`, then `stores_raw.json`.
5. **Review routing** — stores go to human review if `auto_review.decision == "needs_human"`, or if there is no auto-review result and the store is Tier 3.
6. **Two Firebase targets**:
   - Default project (`firebase_key.json`) for the store-extract app (`POST /jobs/{id}/approve`).
   - `traders-data-live` project (`traders_data_live_key.json`) with a richer schema (`POST /jobs/{id}/traders/push`).
7. **Arabic status labels** returned by the API: `✅ نشط`, `🚫 مقفول`, `⚪ غير محدد`, `⚠️ غير مؤكد`, `⚪ يحتاج تحقق`.
8. **Firebase lazy initialization** — services initialize on first use so the app can boot without valid keys.
9. **Resume flow** — `ResumeBanner` calls `GET /jobs` on mount and lets users resume a previous job into the Zustand store.
10. **No logging framework config** — logs go to stdout; ad-hoc log files are created by utility scripts.

---

## Deployment

A split deployment blueprint is provided:

- **Backend** → Render (`render.yaml`).
- **Frontend** → Vercel (detected automatically from `frontend/`).

See `DEPLOY.md` for detailed Render + Vercel setup, environment variables, and secret files.

If deploying in the future, at minimum you will need to:

- Keep service-account keys out of the repo and mount them as secrets (already gitignored).
- Decide whether the pipeline (`../pipeline/`) will be bundled or remain a sibling directory.
- Replace SQLite with a proper database if running multiple backend workers.

---

## Common gotchas

- The backend README still mentions the old path `d:/sharea elnassim/backend`; the project now lives in `d:/sharea elnassim/extract stores/`.
- The README also says "Pipeline v5 and v6 are not wired yet" and "jobs are stored in memory" — these statements are outdated. v5/v6 are invoked by `runner.py` and jobs are persisted in SQLite.
- `frontend/.env.development` is environment-specific; do not overwrite it with defaults that break another developer's setup.
- On Windows, always run the backend before the frontend; the frontend needs the API on `:8000`.
