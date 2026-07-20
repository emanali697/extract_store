# Ngrok demo guide — test the system without a server

Use this when you want someone to try the frontend from anywhere while the backend still runs on your local machine. No credit card needed.

## What you need

- A Vercel account (free).
- An ngrok account (free).
- The project running locally on your Windows machine.

## Step 1 — Install ngrok

1. Go to [ngrok.com](https://ngrok.com) and create a free account.
2. Download ngrok for Windows.
3. Extract `ngrok.exe` to a folder and add it to your PATH, or keep it in a known folder.
4. Open PowerShell or Git Bash and run the auth command from your ngrok dashboard:
   ```powershell
   ngrok config add-authtoken YOUR_TOKEN_HERE
   ```

## Step 2 — Deploy the frontend on Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project**.
2. Import `emanali697/extract_store`.
3. Vercel should detect it as a Vite project.
4. Add this environment variable:
   ```env
   VITE_API_BASE_URL=https://temporary.ngrok.url
   ```
   (Use any placeholder for now; you will replace it later.)
5. Click **Deploy**.
6. Copy the Vercel URL, e.g.:
   ```text
   https://extract-store-something.vercel.app
   ```

## Step 3 — Start the backend locally

1. Open PowerShell and run:
   ```powershell
   cd "D:/sharea elnassim/extract stores/backend"
   venv\Scripts\activate
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```
   (Use `python -m venv venv` first if `venv` does not exist.)

2. Make sure your `backend/.env` file has the Vercel URL in `ALLOWED_ORIGINS`:
   ```env
   FIREBASE_KEY_PATH=firebase_key.json
   FIRESTORE_COLLECTION=stores
   TRADERS_KEY_PATH=traders_data_live_key.json
   TRADERS_COLLECTION=stores
   UPLOAD_DIR=uploads
   JOBS_DIR=jobs
   PIPELINE_DIR=../pipeline
   ALLOWED_ORIGINS=https://extract-store-something.vercel.app,http://localhost:5173
   ```
   Replace `https://extract-store-something.vercel.app` with your real Vercel URL.

## Step 4 — Start ngrok

1. Open a second PowerShell window.
2. Run:
   ```powershell
   ngrok http 8000
   ```
3. Copy the **Forwarding** URL, for example:
   ```text
   https://abc123-def.ngrok-free.app
   ```

## Step 5 — Update Vercel to point at ngrok

1. In Vercel dashboard, open your project.
2. Go to **Settings → Environment Variables**.
3. Change `VITE_API_BASE_URL` to your ngrok URL:
   ```env
   VITE_API_BASE_URL=https://abc123-def.ngrok-free.app
   ```
4. Go to **Deployments** and click the latest deployment, then **Redeploy**.

## Step 6 — Test

1. Open the Vercel URL in any browser.
2. Upload a video.
3. The backend on your machine will process it.

## Important notes

- Your computer must stay on and ngrok must keep running.
- The free ngrok URL changes every time you restart ngrok. If it changes, repeat Step 5.
- All uploaded files, SQLite data, and pipeline output stay on your machine.
- This is for demo only; for production, deploy the backend on a real server (Render, Railway, etc.).
