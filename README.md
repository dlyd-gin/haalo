# Haalo App

A travel conversation app: type or speak on your side, and the other person reads or hears the reply in
their language, with on-device open-weight models. See [docs/introduction.md](docs/introduction.md) for the
idea and [docs/architecture.md](docs/architecture.md) for how it fits together.

The frontend is an Angular 21 app (generated with [Angular CLI](https://github.com/angular/angular-cli)
version 21.2.20) running on Node.js 22.22.0, served by an Express/SSR server (`src/server.ts`) that
proxies to Python services in `services/`.

## Backend services

Each service has its own README with setup (models are downloaded manually) and API docs. They are
Apple Silicon (MLX) only and need [uv](https://docs.astral.sh/uv/).

| Service | Port | Purpose |
| --- | --- | --- |
| [tts-service](services/tts-service/README.md) | 8000 | text to speech |
| [translator-service](services/translator-service/README.md) | 8001 | translation, document grounding and suggestions |
| [stt-service](services/stt-service/README.md) | 8002 | speech to text |
| [document-service](services/document-service/README.md) | 8003 | PDF / Word / image document processing |
| [ocr-service](services/ocr-service/README.md) | 8004 | image text recognition with bounding boxes |

## Development server

Use nvm to set node version 22.22.0 (`nvm install && nvm use` reads `.nvmrc`)

To start Angular and every Python service together, run:

```bash
npm run start-dev
```

(`start-dev.sh`; it runs `ng serve` plus all five services with `uv run uvicorn ...`, and stops them all
on Ctrl+C.) To run just the frontend, use `ng serve`.

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Running with SSR (Node server)

To run the app through its actual Express/SSR server (`src/server.ts`) instead of Angular's
dev-time SSR renderer — e.g. to exercise the real `/api/tts`, `/api/stt`, `/api/translate`, `/api/pdf/analyze`
and `/api/document/*` proxy routes to the backend Python services — run these two commands in separate terminals:

```bash
# terminal 1 — rebuilds dist/ on source changes
ng build --watch --configuration development

# terminal 2 — restarts the Express/SSR server whenever the built bundle changes
node --watch dist/haalo-app/server/server.mjs
```

This listens on `http://localhost:4000/` by default (override with `PORT=<n>`) — a different
port from `ng serve`'s 4200, so both commands can run side by side if you want to compare SSR vs.
browser-only rendering.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

Each Python service has its own `uv run pytest` where tests exist (e.g. `services/ocr-service`).

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
