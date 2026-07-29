"""Set CORS rules on the Firebase Storage bucket."""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.cloud import storage
from google.oauth2 import service_account

# Use the service account key for the store-extract project.
key_path = Path(__file__).resolve().parent / "firebase_key.json"
if not key_path.exists():
    raise SystemExit(f"Service account key not found: {key_path}")

credentials = service_account.Credentials.from_service_account_file(str(key_path))
client = storage.Client(credentials=credentials, project="store-extract")

bucket_name = "store-extract.firebasestorage.app"
bucket = client.bucket(bucket_name)

# CORS configuration allowing localhost (dev) and Vercel production.
cors_config = [
    {
        "origin": ["http://localhost:5173", "https://extract-store.vercel.app"],
        "method": ["PUT", "POST", "GET", "OPTIONS", "DELETE"],
        "maxAgeSeconds": 3600,
        "responseHeader": [
            "Content-Type",
            "Authorization",
            "x-goog-resumable",
            "x-goog-upload-command",
            "x-goog-upload-status",
            "x-goog-upload-url",
            "Access-Control-Allow-Origin",
        ],
    }
]

bucket.cors = cors_config
bucket.patch()

print(f"CORS configured for bucket: {bucket_name}")
print(json.dumps(cors_config, indent=2))
