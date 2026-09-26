# Trace backend

Install the locked dependencies before starting the backend directly:

```bash
uv sync --locked
```

Then run:

```bash
./start.sh
```

The startup script runs only the already-locked dependency set. It does not download packages or update `uv.lock`.
