# Lumora

A learning project covering Docker, microservices, CI/CD, and Kubernetes,
using a dating-app concept site as the example codebase.

## Architecture

```
   Browser
     │
     ▼
   ┌──────────┐    ┌──────────┐    ┌──────────────┐
   │ lumora-  │───▶│ lumora-  │───▶│  lumora-db   │
   │   web    │    │   api    │    │ (postgres)   │
   │ (nginx)  │    │(FastAPI) │    │              │
   └──────────┘    └──────────┘    └──────────────┘
                                          │
                                          ▼
                                    [ named volume ]
```

## Running locally

```bash
docker compose up --build
```

Then visit:
- http://localhost:8090 - the Lumora website
- http://localhost:8000/profiles - raw API
- http://localhost:8000/docs - interactive API docs

## Running tests

```bash
cd api
pip install -r requirements.txt
pytest -v
```

## CI/CD

Every push to `main` triggers `.github/workflows/ci.yml`:

1. Run the API test suite
2. If tests pass and we're on `main`, build the Docker images
3. Push them to Docker Hub tagged with `:latest` and the commit SHA
