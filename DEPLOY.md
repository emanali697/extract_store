# Deployment guide — Firebase Functions backend + Vercel frontend

> **Before you deploy:** read [`FIREBASE_CONFIG.md`](./FIREBASE_CONFIG.md) for the exact values you need to fill (Firebase web API key, Cloud Functions env vars, traders secret, etc.).

This project uses:

- **Frontend** (React + Vite) → Vercel
- **Backend** (Firebase Functions + Cloud Storage + Firestore) → Firebase

The previous Render backend deployment is now replaced by Firebase Functions.

---

## 1. Firebase project setup

1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Open the project `store-extract`.
3. Enable the following APIs in **Google Cloud Console** for the same project:
   - Cloud Functions API
   - Cloud Run API (required by Cloud Functions 2nd gen)
   - Cloud Tasks API
   - Cloud Pub/Sub API
   - Cloud Firestore API
   - Cloud Storage API
   - Cloud Vision API
   - Vertex AI API
   - Places API (New)

4. In Firebase Console, enable **Firestore** and **Storage**.
5. Create a **Cloud Storage bucket** if it does not exist. The default bucket is `store-extract.appspot.com`.
6. Firebase deploy creates the `runpipelinetask` Cloud Tasks queue. The
   `run-pipeline` Pub/Sub topic is retained only for compatibility with jobs
   queued before the Cloud Tasks migration.

### Vertex AI permission

The identity that runs the pipeline must have the **Vertex AI User**
role (`roles/aiplatform.user`) in `store-extract`. Without it, Gemini returns
`403 PERMISSION_DENIED` and no stores can be extracted.

For deployed 2nd-gen Firebase Functions, grant the role to the default Compute
Engine runtime service account:

```powershell
$projectNumber = gcloud projects describe store-extract --format="value(projectNumber)"
$runtimeServiceAccount = "$projectNumber-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding store-extract `
  --member="serviceAccount:$runtimeServiceAccount" `
  --role="roles/aiplatform.user"
```

For local FastAPI development with `backend/firebase_key.json`, grant the same
role to the service account referenced by that key:

```powershell
$localServiceAccount = (Get-Content backend/firebase_key.json | ConvertFrom-Json).client_email
gcloud projects add-iam-policy-binding store-extract `
  --member="serviceAccount:$localServiceAccount" `
  --role="roles/aiplatform.user"
```

---

## 2. Configure environment variables and secrets

### Service accounts

The default Firebase project uses the runtime service account, so no key file is needed for the main project.

For the **traders-data-live** project, you need to provide the service account key. In Firebase Console, go to **Functions secrets** and create a secret named:

```text
TRADERS_SERVICE_ACCOUNT_JSON
```

Paste the full JSON content of `traders_data_live_key.json` as the value.

### Environment variables

In `firebase.json` or via `firebase functions:config:set`, set:

```bash
firebase functions:config:set \
  app.allowed_origins="https://extract-store.vercel.app,http://localhost:5173" \
  app.gcp_project_id="store-extract" \
  app.pipeline_topic="run-pipeline" \
  app.storage_bucket="store-extract.firebasestorage.app" \
  app.firestore_collection="stores" \
  app.traders_collection="stores"
```

Note: in the current code, environment variables are read from `process.env`. With Firebase Functions config, they are prefixed with `app.` and accessed as `process.env.app_...`. Update `functions/config.py` if you use Functions config instead of plain environment variables.

---

## 3. Deploy Firebase Functions

From the repo root:

```powershell
cd "D:/sharea elnassim/extract stores"
firebase login
firebase deploy --only functions,storage
```

The first deploy may take several minutes because the pipeline dependencies (opencv-python, google-cloud-vision, google-genai, etc.) are large.

---

## 4. Deploy the frontend on Vercel

1. Go to [vercel.com](https://vercel.com) and import the same GitHub repo.
2. Vercel should auto-detect the `frontend/` folder as a Vite project.
3. In **Environment Variables**, add:

```env
VITE_API_BASE_URL=https://us-central1-store-extract.cloudfunctions.net
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=store-extract.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=store-extract
VITE_FIREBASE_STORAGE_BUCKET=store-extract.firebasestorage.app
VITE_FIREBASE_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
```

Use the actual Firebase Functions URL from the deploy step.

4. Deploy.

---

## 5. Local development with Firebase emulators

Install the Firebase emulators if not already installed:

```powershell
firebase emulators:start --only functions,firestore,storage,pubsub
```

In another terminal, start the frontend:

```powershell
cd frontend
npm run dev
```

Make sure `frontend/.env.development` points to the emulator:

```env
VITE_API_BASE_URL=http://127.0.0.1:5001/store-extract/us-central1
```

---

## 6. Important notes

- The ML pipeline is copied into `functions/pipeline/` during deployment.
- Videos of 64 MB or more are uploaded directly to Firebase Storage in parallel
  chunks, composed by `complete_upload`, and removed automatically after the
  worker finishes. Only final JSON/Excel files and sign images required for
  human review are retained.
- Deploy Storage rules together with Functions; otherwise multipart uploads
  under `jobs/{jobId}/upload_parts/` will be denied.
- Storefront names and phones are read directly from sign images with Gemini.
  Cloud Vision remains in use only for the GPS/speed overlay.
- Progress is streamed to the frontend via Firestore snapshots.
- The primary pipeline worker runs through Cloud Tasks with a 30-minute
  dispatch deadline, 4 GB memory, concurrency 1, and up to 3 instances. Very
  large videos that need more than 30 minutes must be split or moved to a
  longer-running compute service.
- Cloud Vision, Gemini, and Places API billing is separate from Firebase Functions billing.

---

## 7. Verify deployment

Open the health endpoint:

```text
https://us-central1-store-extract.cloudfunctions.net/health
```

You should see JSON with `firebase`, `traders`, and `pipeline` status.

Then upload a video from the frontend and verify the pipeline completes.
