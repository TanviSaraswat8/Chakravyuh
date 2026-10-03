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

## Any Docker host

```bash
docker compose up --build -d
```

This runs PostgreSQL, the API on port 8000 and the web app on port 8080 (nginx proxies `/v1` to the API). Put a reverse proxy with HTTPS in front for anything public.

## Vercel or Netlify for the web app only

Build command `npm run build`, output directory `dist`, root directory `frontend`, and set `VITE_API_URL` to the API URL. Add a rewrite of all paths to `/index.html` so page refreshes work.

## Updating the models

Train locally (`make data && make train`), commit `backend/artifacts/`, and push. The API loads the new models on its next deploy.
