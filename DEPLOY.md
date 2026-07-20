# Deployment guide — Render backend + Vercel frontend

This project uses a split deployment:

- **Frontend** (React + Vite) → Vercel
- **Backend** (FastAPI + Python pipeline) → Render

---

## 1. Deploy the backend on Render

1. Go to [render.com](https://render.com) and sign in with GitHub.
2. Click **New +** → **Web Service**.
3. Connect the `emanali697/extract_store` repo.
4. Render should auto-detect `render.yaml` and fill these fields:
   - **Name:** `extract-store-backend`
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port ${PORT}`

### Required environment variables

In the Render dashboard, open **Environment** and add:

```env
FIREBASE_KEY_PATH=firebase_key.json
FIRESTORE_COLLECTION=stores
TRADERS_KEY_PATH=traders_data_live_key.json
TRADERS_COLLECTION=stores
UPLOAD_DIR=uploads
JOBS_DIR=jobs
PIPELINE_DIR=../pipeline
PYTHONUNBUFFERED=1
ALLOWED_ORIGINS=https://your-frontend-url.vercel.app,http://localhost:5173
```

Replace `https://your-frontend-url.vercel.app` with your actual Vercel frontend URL after deploying it.

### Required secret files

In Render dashboard, go to **Environment > Secret Files** and upload:

- `firebase_key.json` → content of your Firebase service account key.
- `traders_data_live_key.json` → content of your traders-data-live service account key.

These files appear inside `backend/` at runtime.

### The pipeline

The ML pipeline lives **outside** this repo (`../pipeline/`). On Render you must either:

- Include the `pipeline/` folder inside the repo (for example at `backend/pipeline/`), or
- Upload the pipeline files to Render using SSH/disks (advanced).

If you place the pipeline inside `backend/pipeline/`, set `PIPELINE_DIR=pipeline` instead of `../pipeline`.

### Verify deployment

Open:

```text
https://extract-store-backend.onrender.com/health
```

You should see JSON with `firebase`, `traders`, and `pipeline` status.

---

## 2. Deploy the frontend on Vercel

1. Go to [vercel.com](https://vercel.com) and import the same GitHub repo.
2. Vercel should auto-detect the `frontend/` folder as a Vite project.
3. In **Environment Variables**, add:

```env
VITE_API_BASE_URL=https://extract-store-backend.onrender.com
```

Use the actual Render backend URL from step 1.

4. Deploy.

---

## 3. Local development

For local development the default API URL is `http://localhost:8000`.

Copy `frontend/.env.example` to `frontend/.env.development` and fill in your local backend URL if needed.

Copy `backend/.env.example` to `backend/.env` and fill in your Firebase key paths.
