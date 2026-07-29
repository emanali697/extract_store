# Firebase Configuration Guide — Store Extractor

This guide explains every value you need to fill before the Firebase Functions backend and Vercel frontend can talk to each other.

---

## 1. Files that control the config

| File | What it is | When you edit it |
|---|---|---|
| `.firebaserc` | Tells Firebase CLI which project to use | Already set to `store-extract` |
| `firebase.json` | Functions + emulator ports | Already set, do not change unless you know why |
| `functions/.env.example` | Cloud Functions environment variables | Copy to `functions/.env` for local emulator; set via CLI for production |
| `frontend/.env.example` | Frontend Firebase web config | Copy to `frontend/.env.development` (local) and add to Vercel (production) |

---

## 2. Frontend Firebase web config

Open [Firebase Console](https://console.firebase.google.com/) and select project **store-extract**.

1. Click the gear icon → **Project settings** → **General**.
2. Scroll to **Your apps** and choose the **Web app** (`</>`). If you don't have one, click the web icon and register a new app called `store-extractor-web`.
3. Copy these values into `frontend/.env.development` (and later into Vercel environment variables):

```env
VITE_FIREBASE_API_KEY=AIza...          # apiKey
VITE_FIREBASE_AUTH_DOMAIN=store-extract.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=store-extract
VITE_FIREBASE_STORAGE_BUCKET=store-extract.appspot.com
VITE_FIREBASE_SENDER_ID=123456789012  # messagingSenderId
VITE_FIREBASE_APP_ID=1:123...:web:... # appId
```

> The `API key`, `messagingSenderId`, and `appId` are the only three values you must paste from the console. The rest are already filled in `frontend/.env.example`.

### Local frontend

```powershell
cd "D:/sharea elnassim/extract stores/frontend"
copy .env.example .env.development
# edit .env.development and paste the three values
npm run dev
```

### Production frontend (Vercel)

In your Vercel project settings → **Environment Variables**, add the same keys, but use the production Functions URL:

```env
VITE_API_BASE_URL=https://us-central1-store-extract.cloudfunctions.net
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=store-extract.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=store-extract
VITE_FIREBASE_STORAGE_BUCKET=store-extract.appspot.com
VITE_FIREBASE_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
```

---

## 3. Cloud Functions environment variables

### Local emulator

```powershell
cd "D:/sharea elnassim/extract stores/functions"
copy .env.example .env
# Edit .env and fill in the values you need.
```

You usually only need to change these:

```env
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://extract-store.vercel.app
PIPELINE_PYTHON=C:/Users/Admin/AppData/Local/Programs/Python/Python312/python.exe
```

The emulator sets `FIRESTORE_EMULATOR_HOST`, `STORAGE_EMULATOR_HOST`, etc. automatically, so you can leave those commented out.

### Production deploy

Set each variable with the Firebase CLI:

```powershell
cd "D:/sharea elnassim/extract stores"
firebase functions:env:set GCP_PROJECT_ID=store-extract
firebase functions:env:set GCP_LOCATION=us-central1
firebase functions:env:set FIRESTORE_COLLECTION=stores
firebase functions:env:set JOBS_COLLECTION=jobs
firebase functions:env:set TRADERS_COLLECTION=stores
firebase functions:env:set STORAGE_BUCKET=store-extract.appspot.com
firebase functions:env:set PIPELINE_TOPIC=run-pipeline
firebase functions:env:set ALLOWED_ORIGINS=https://extract-store.vercel.app,http://localhost:5173
```

> You do **not** set `TRADERS_SERVICE_ACCOUNT_JSON` as a plain env var. See step 4 below.

---

## 4. Traders service account secret

The Cloud Functions need to write to a second Firebase project called `traders-data-live`. The key for that project must be provided as a **Firebase Secret**, not as a plain text env var.

1. Make sure you have the file `traders_data_live_key.json` (the one you used in the old backend).
2. Create the secret in Firebase:

```powershell
firebase functions:secrets:create TRADERS_SERVICE_ACCOUNT_JSON
```

When prompted, paste the **entire contents** of `traders_data_live_key.json` as the secret value.

3. Deploy the functions so they can access the secret:

```powershell
firebase deploy --only functions
```

### Local emulator only

For local testing you can paste the JSON directly into `functions/.env` (one line):

```env
TRADERS_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

**Do not commit this file.** It is already ignored by `functions/.gitignore`.

---

## 5. Required Google Cloud APIs

Before deploying, enable these APIs in [Google Cloud Console](https://console.cloud.google.com/) for project `store-extract`:

- Cloud Functions API
- Cloud Run API (needed by 2nd gen functions)
- Cloud Pub/Sub API
- Cloud Firestore API
- Cloud Storage API
- Cloud Vision API (used by the pipeline)
- Places API (New) (used by the pipeline)

Also create a Pub/Sub topic named `run-pipeline`:

```powershell
gcloud pubsub topics create run-pipeline --project=store-extract
```

---

## 6. Local emulator quick start

```powershell
# Terminal 1: backend emulator
cd "D:/sharea elnassim/extract stores"
firebase emulators:start --only functions,firestore,storage,pubsub

# Terminal 2: frontend
cd "D:/sharea elnassim/extract stores/frontend"
npm run dev
```

Make sure `frontend/.env.development` points to the emulator:

```env
VITE_API_BASE_URL=http://127.0.0.1:5001/store-extract/us-central1
```

---

## 7. Production deploy checklist

- [ ] `frontend/.env.development` has the three Firebase web values filled.
- [ ] Vercel environment variables use production `VITE_API_BASE_URL`.
- [ ] Cloud Functions env vars are set via `firebase functions:env:set`.
- [ ] `TRADERS_SERVICE_ACCOUNT_JSON` secret is created.
- [ ] Google Cloud APIs are enabled.
- [ ] Pub/Sub topic `run-pipeline` exists.
- [ ] Firestore and Storage are enabled in Firebase Console.
- [ ] Run `firebase deploy --only functions` and wait for the first deploy to finish (it is slow because of opencv/google-cloud-vision).

---

## 8. Security note

You pasted a Firebase Admin SDK service-account JSON (`firebase_key.json` for project `store-extract`) into an earlier chat. Treat that key as compromised. Go to **Google Cloud Console > IAM & Admin > Service Accounts**, find `firebase-adminsdk-fbsvc@store-extract.iam.gserviceaccount.com`, create a new key, download it, and delete the old key. Replace `backend/firebase_key.json` with the new key before any deploy.

---

## 9. Where each config value lives

| Config | Set in | Needed by |
|---|---|---|
| Firebase web API key / appId / senderId | `frontend/.env.development`, Vercel | Frontend only |
| Functions URL | `frontend/.env.development`, Vercel | Frontend only |
| Firestore/Storage/PubSub project IDs | Cloud Functions env vars / runtime | Functions only |
| Traders service account JSON | Firebase Secret `TRADERS_SERVICE_ACCOUNT_JSON` | Functions only |
| Pipeline Python path | `functions/.env` (local) | Local emulator only |
| CORS origins | `ALLOWED_ORIGINS` env var | Functions only |
