## Trace

Trace is AI agent that scans your vibe-coded apps for security vulnerabilities and pre-launch mistakes that could cost you or your users when you hit production. The agentic era has given anyone the ability to build an entire application end-to-end without needing technical or product expertise.

But to launch an app on any platform, there are technical, product and legal decisions to be made to prevent you or your users from being compromised. Trace exposes those gaps present in your app that need your attention before launching to the market.

Trace is built for the non-technical builders who lack the technical and product expertise for successfully launching in application on a production environment and into the market.


## System Architecture

On a high level, Trace will operate with the client-server model, with the server layer being a combination of a relational database, API server and a cache (for saving frequently accessed data). 


## Tech Stack 

- React: The library of choice for building the user interface for Trace, with the Typescript programming language. React was chosen because it the most popular library for building user-interfaces with huge community support.

- Fast API: The library of choice for building the API server, with the Python programming language. FastAPI makes it easy and flexible to build APIs in Python.

- PostgreSQL: The relational database of choice for storing data.

- Redis: The cache client for saving frequently-accessed data to improve API server performance.

- Langchain/Langgraph: For building and orchestrating AI agents and coordinating AI workflows.

- Langsmith: For adding observabilty to AI agent and workflow runs to ensure reliability of results and findings.

- Sentry: For error monitoring and observability of API serve and user interface to ensure reliability of the platform.

## Local services

Phase 1 runs the FastAPI backend, PostgreSQL, Redis, and Mailpit with Docker Compose.

1. Copy `.env.example` to `.env` and replace the local PostgreSQL password in both `POSTGRES_PASSWORD` and `DATABASE_URL` with the same URL-safe value.
2. Start the stack and wait for all service health checks:

   ```bash
   docker compose up --build --wait
   ```

3. Open the FastAPI health endpoint at [http://localhost:8000/health](http://localhost:8000/health) and the Mailpit inbox at [http://localhost:8025](http://localhost:8025).

PostgreSQL, Redis, and Mailpit SMTP are available only on the private Docker networks. The backend connects to them as `postgres`, `redis`, and `mailpit` respectively.

Stop the stack cleanly with:

```bash
docker compose down
```

This preserves PostgreSQL data. Use `docker compose down -v` only when you intentionally want to delete local database data.

The backend container runs [start.sh](backend/start.sh) with locked dependencies and without runtime downloads. It is non-root, has a read-only filesystem, cannot gain new privileges, and exposes only the API port on localhost. Service images are pinned to immutable digests; update them deliberately as part of maintenance.
