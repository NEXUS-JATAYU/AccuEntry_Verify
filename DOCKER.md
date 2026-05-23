# Docker — AccuVerify

## Ports

| Where | Port |
|-------|------|
| **Inside container** | `8080` (Cloud Run standard) |
| **On your PC (mapped)** | `9000` → same as local `uvicorn --port 9000` |

Host ports 8080/8081 stay free for your other apps.

---

## 1. Prepare `.env`

Copy from `.env.example`:

```env
MONGO_DB_URL=mongodb://host.docker.internal:27017
# or Atlas: mongodb+srv://...
REDIS_URL=redis://host.docker.internal:6379/0
REQUIRE_VERIFY_SERVICE_KEY=false
```

---

## 2. Build

```powershell
cd AccuEntry_Verify
docker build -t accuverify:local .
```

First build may take 15–30 minutes (TensorFlow / DeepFace).

---

## 3. Run (option A — docker compose)

```powershell
docker compose up --build
```

API: http://localhost:9000/  
Health: http://localhost:9000/health

---

## 4. Run (option B — docker run)

```powershell
docker run --rm -p 9000:8080 --env-file .env `
  --add-host=host.docker.internal:host-gateway `
  accuverify:local
```

---

## 5. Smoke test

```powershell
curl http://localhost:9000/health
```

---

## With Backend container

1. Start Verify: `docker compose up` in **AccuEntry_Verify** (port 9000)
2. Start Backend with `ACCUVERIFY_URL=http://host.docker.internal:9000`

---

## Push to GCP

```bash
gcloud builds submit . --tag REGION-docker.pkg.dev/PROJECT/accuentry/verify:latest
```
