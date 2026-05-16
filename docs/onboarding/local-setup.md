# Local setup

## Prerequisites

| Tool | Version | Install hint |
|---|---|---|
| Docker | 24+ | https://docs.docker.com/get-docker/ |
| Docker Compose v2 | — | bundled with Docker Desktop / `docker compose plugin` |
| Node | 22 LTS | `nvm install` (uses `.nvmrc`) |
| pnpm | 9.x | `corepack enable && corepack prepare pnpm@9 --activate` |
| Python | 3.12 | `pyenv install 3.12` (uses `.python-version`) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Make | any | preinstalled on macOS/Linux |

## First-time bootstrap

```bash
git clone git@github.com:yupay/yupay.git
cd yupay
make bootstrap   # installs all deps, sets up pre-commit, generates api-client
```

## Running the stack

```bash
make dev         # full docker-compose stack
```

- API: https://api.localhost (internal Caddy TLS) or http://localhost:8000
- Web: http://localhost:3000
- Mini App: http://localhost:3001
- Mailhog UI: http://localhost:8025
- Adminer (DB GUI): http://localhost:8080
- Grafana (in prod compose): https://grafana.yupay.io

## Common commands

```bash
make test
make lint
make typecheck
make migrate
make migration name=add_orders_index
make gen-api
make logs service=api
```

## Editor

VS Code + the following recommended extensions (will be prompted on open):

- Python (Microsoft)
- Pylance
- Ruff
- ESLint
- Prettier
- Tailwind CSS IntelliSense

## Troubleshooting

- **Port already in use**: another instance is running. `make down` or `docker compose down`.
- **`uv: command not found`**: re-run the install script and reopen the shell.
- **Pre-commit fails on first commit**: run `pre-commit run --all-files` to see all errors at once.
- **OpenAPI drift**: run `make gen-api` and commit the regenerated files.
