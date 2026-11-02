# Contributing to MascotForge

Thanks for helping. Bug reports, fixes, new state presets, documentation and
translations are all welcome. Issues and pull requests in English or French are
fine.

## Before you start

- For a small fix (a typo, a clear bug), open a pull request directly.
- For anything bigger (a new engine, a new API route, a change to the export
  format), open an issue first and describe what you want to change and why.
  You will know whether it fits before you write the code.
- Look for an existing issue on the same topic before opening a new one.

## Set up

```bash
git clone https://github.com/Arivex-ca/mascotforge.git
cd mascotforge
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m uvicorn backend.main:app --port 8766
```

The studio opens at `http://localhost:8766/`. Blob and 3D mascots need no API
key. Some features need system tools:

| Tool | Used for | Without it |
|---|---|---|
| ffmpeg and ffprobe | green-screen removal for AI video | clips keep their green background |
| Chrome or Edge | blob and 3D previews | the preview routes report an error |
| Node 18 or newer | the Wobnimo checker for 3D characters | 3D checks and image-to-3D return an error |

## Run the tests

```bash
.venv/bin/python -m pytest
```

All tests must pass before a pull request is merged. fal.ai is mocked, so the
suite makes no network call and spends nothing. A few tests skip when ffmpeg,
Node or Playwright is missing; that is expected.

`tests-reels/test_1_clip.py` is different: it generates a real Kling clip and
costs about $0.25 on your own fal account. Pytest collects the file but runs
nothing from it. Run it by hand
only if you changed `backend/fal.py`, and only with your own `FAL_KEY`.

Add a test for every bug you fix and every behavior you add. Look at the
existing file closest to your change (`tests/test_api.py` for routes,
`tests/test_agent_blobs.py` for custom blobs, and so on).

## Project layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI server: pipeline, engines, blob and 3D checks, exports |
| `mascotforge/` | CLI and MCP server for agents |
| `studio/` | the studio UI (plain HTML, CSS and JavaScript) |
| `widget/` | `<mascot-avatar>`, copied into every export |
| `engines/` | third-party engines, vendored with their licenses |
| `skills/mascotforge/` | the Agent Skills skill for coding agents |
| `tests/` | the pytest suite |

## Rules

- **Keys stay out of URLs, logs, files and responses.** A key travels only in
  the `X-Fal-Key` or `X-OpenRouter-Key` header and lives in the request context.
  Never add a key to a query string, a job file, an error message or a log line.
- **Third-party engines keep their license.** Files under `engines/` come from
  Blob Atelier (Victoria Wu) and Wobnimo (Pourya Akhbari), both MIT. Do not edit
  them in passing. If an engine needs a patch, keep it minimal, explain it in
  `engines/README.md` and update the SHA-256 there.
- **No em dash (U+2014) in user-facing text.** Error messages, the studio and
  exported READMEs use colons, semicolons or a new sentence instead. Some tests
  check for it.
- **Every button gives feedback.** A visible pressed state, a loading state for
  async actions, a visible error message on failure, and `focus-visible` styles.
- **Match the surrounding code.** Comments in the existing code are in French;
  English is fine in new code. Keep changes focused: one pull request, one
  purpose.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Make your change and run `pytest`.
3. Open a pull request that says what changed, why, and how you tested it.
   Screenshots help for any change to the studio or the widget.
4. Answer review comments with new commits; the maintainer squashes or merges.

## Security

If you find a security problem, such as a way to read someone's key or to spend
someone else's fal credit, do not describe it in a public issue. Open an issue
titled "Security contact" with no details, and the maintainer will reply with a
private channel.

## License

By contributing, you agree that your contribution is released under the MIT
License of this project (see `LICENSE`).
