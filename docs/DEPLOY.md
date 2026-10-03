# Deploying Chakravyuh

The repo includes a Render blueprint (`render.yaml`) that creates the PostgreSQL database, the API and the web app in one go. Any Docker host works the same way.

## Render (recommended for the hackathon)

1. Push the repo to GitHub.
2. In Render, choose **New > Blueprint** and select the repo. Render reads `render.yaml`.
3. Check the two URLs in `render.yaml` match your service names:
   - `CORS_ORIGINS` on the API must be the web app's URL.
   - `VITE_API_URL` on the web app must be the API's URL.
4. Deploy. The API image installs CPU-only PyTorch and generates simulator data during the build (a few minutes the first time).
5. Open `https://<api>.onrender.com/health`. You should see `"loaded": true`.
6. Run the smoke test against it (standard library only, nothing to install):

   ```bash
   python3 scripts/smoke_test.py https://<api>.onrender.com
   ```

   It checks 14 things end to end: models loaded, scams escalate, look-alikes stay quiet, a live
   session is scored and stored, privacy mode works, beta sign-up and feedback work.

The API needs about 1 GB of RAM because it loads PyTorch and the models, so use the Starter plan or above. The free plan (512 MB) runs out of memory.

### Environment variables (API)

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string (Render fills this in) |
| `ADMIN_API_KEY` | Key for analyst-only routes (Render generates it; find it in the dashboard) |
| `CORS_ORIGINS` | Comma-separated web origins allowed to call the API |
| `REQUIRE_API_KEY` | `true` for the public beta, so only signed-up testers can write data |
| `STORE_MESSAGE_TEXT` | `false` in production: text is scored in memory and never stored |
| `CHAKRAVYUH_LLM_*` | Optional LLM for the simulator's attacker agents |

## Validate the whole stack locally first

On Windows with Docker Desktop running, from the repo folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_docker.ps1
```

It checks Docker, pulls the latest code, stops any previous Chakravyuh stack, builds both images,
starts PostgreSQL + API + web and waits until all three are healthy (if one fails to start it stops
there and prints that container's status, exit code, restarts and log errors), then runs the smoke test through nginx, the regression checks
(Customs hold, flat deposit), attacker evolution and the defender's update, campaign detection,
persistence across an API restart, privacy mode checked inside PostgreSQL, and the full test
suite inside the API image against PostgreSQL. It writes `validation-report.txt` and leaves the
stack running at http://localhost:8080. The first build downloads about 1 GB.

If port 8000 or 8080 is taken, the script picks the next free port and says so in the report. To
choose yourself, set `API_HOST_PORT` or `WEB_HOST_PORT` first, for example `$env:WEB_HOST_PORT = "8081"`.

PostgreSQL publishes no port on your machine, so another PostgreSQL on 5432 (or another project's
database container) never blocks the stack. To connect with psql or VS Code, start with the override:
`docker compose -f docker-compose.yml -f docker-compose.dbport.yml up -d` and use `localhost:55432`.

## Any Docker host

```bash
docker compose up --build -d --wait
```

This runs PostgreSQL, the API on port 8000 and the web app on port 8080 (nginx proxies `/v1` to the API). Put a reverse proxy with HTTPS in front for anything public.

## Vercel or Netlify for the web app only

Build command `npm run build`, output directory `dist`, root directory `frontend`, and set `VITE_API_URL` to the API URL. Add a rewrite of all paths to `/index.html` so page refreshes work.

## What CI checks on every push

GitHub Actions (`.github/workflows/ci.yml`) lints and tests the backend, builds the frontend, then
runs the same full-stack Docker checks as the validation script: real images, PostgreSQL, nginx,
smoke test, regression checks, privacy mode in the database and the test suite against PostgreSQL.
A green run means the images you deploy actually start and work.

## One process per API instance

Run the API as a single process per instance (the default `CMD`). The arena's attacker population
and any defender update made from the web arena live in that process's memory; use
`make coevolve PERSIST=1` to make an update permanent.

## Updating the models

Train locally (`make data && make train`), commit `backend/artifacts/`, and push. The API loads the new models on its next deploy.
