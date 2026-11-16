# MascotForge technical reference

This page contains the implementation, security, API, provider, and agent details removed from the main README.

[Back to the README](../README.md) · [Visual gallery](gallery.md) · [French reference](technical-reference.fr.md)

## Requirements and runtime

- Python 3.10 or newer
- ffmpeg and ffprobe on the PATH, or `MASCOTFORGE_FFMPEG`
- Node 18 or newer for Wobnimo checking and rendering
- Chrome or Edge for visual comparison of image-to-3D results
- A fal.ai key for AI video
- An OpenRouter key only when direct OpenRouter image reading is selected

Without ffmpeg, AI video generation works and keeps the green background. `GET /api/health` reports ffmpeg and server fallback key availability.

Run the server:

```bash
.venv/bin/python -m uvicorn backend.main:app --port 8766 --env-file .env
```

`--env-file` loads `FAL_KEY` and local settings from `.env`. User-owned keys arrive through dedicated headers.

## Key settings and security

The studio accepts a fal.ai key and an optional OpenRouter key.

- Without "Remember on this device," the browser uses `sessionStorage`.
- With that option enabled, the browser uses `localStorage`.
- If the browser blocks storage, the studio keeps the key in memory.
- The browser sends keys in `X-Fal-Key` and `X-OpenRouter-Key` headers.
- `X-Vision-Provider: fal|openrouter` selects the image reader.
- MascotForge does not accept secrets in URLs or query parameters.
- The server does not write keys to jobs, `data/`, logs, exports, or responses.

`FAL_KEY` remains a fallback for a local server. Do not set it on a server that other people can reach. Visitors without their own key would generate video on that account. The monthly cap is also shared by every user of the server.

The key test starts no generation. OpenRouter checks the key through `GET https://openrouter.ai/api/v1/key`. fal.ai uses its storage token request without uploading a file or running inference.

## Agents, CLI, and MCP

The CLI and MCP server use the HTTP API. `MASCOTFORGE_URL` defaults to `http://localhost:8766`. `MASCOTFORGE_FAL_KEY` and `MASCOTFORGE_OPENROUTER_KEY` provide keys through dedicated headers.

### CLI

```bash
python -m mascotforge styles
python -m mascotforge code --engine blob --set shape=cloud --out ./my-blob
python -m mascotforge code --engine 3d --set character=volt --out ./my-robot
python -m mascotforge blob guide --out ./blob-guide.md
python -m mascotforge blob check ./blob.json
python -m mascotforge blob preview ./blob.json --out ./blob-sheet.png
python -m mascotforge blob export ./blob.json --out ./custom-blob
python -m mascotforge image3d ./robot.png --out ./robot-3d
python -m mascotforge video --image ./robot.png --usage agent --out ./robot-video
python -m mascotforge video --prompt "a small orange fox" --usage site --out ./fox
python -m mascotforge status ID
python -m mascotforge export ID --out ./export
python -m mascotforge cost
```

Add `--json` for agent-readable output. `image3d` and `video` are paid. Without `--yes`, they show the estimated price and exit before generation. Run the command again with `--yes` only after the user approves the cost.

### Custom Blob loop

An agent can describe a superellipse and its bumps in a JSON spec. The checker rejects intersections, outlines that are too thin, shapes outside the canvas, and out-of-range values.

```bash
python -m mascotforge blob guide --out ./blob-guide.md
python -m mascotforge blob check ./blob.json
python -m mascotforge blob preview ./blob.json --out ./blob-sheet.png
python -m mascotforge blob export ./blob.json --out ./custom-blob
```

The preview displays every state before export.

### Wobnimo visual loop

An agent that can inspect an image can write a Wobnimo spec without a provider call:

1. Read the guide and inspect the reference image.
2. Write the JSON spec and run the checker.
3. Render the sheet and compare the front view with the source.
4. Correct the spec and repeat the check and preview.
5. Save or export the result.

```bash
python -m mascotforge spec guide --out ./wobnimo-guide.md
python -m mascotforge spec check ./character.json
python -m mascotforge spec preview ./character.json --out ./sheet.png
python -m mascotforge spec save ./character.json
python -m mascotforge spec export ./character.json --out ./character-3d
```

### MCP over stdio

```bash
python -m mascotforge mcp
```

Long-running creations use three calls: a start tool, `mascotforge_status`, then `mascotforge_export`. Paid start tools require `user_confirmed=true`.

The free spec and Blob tools return previews as MCP images so the agent can inspect and correct the result before export.

Claude Desktop configuration in `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mascotforge": {
      "command": "C:\\path\\to\\mascotforge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mascotforge", "mcp"],
      "env": {"MASCOTFORGE_URL": "http://localhost:8766"}
    }
  }
}
```

Cursor uses the same block in `.cursor/mcp.json`.

Codex CLI and app configuration in `~/.codex/config.toml`:

```toml
[mcp_servers.mascotforge]
command = 'C:\path\to\mascotforge\.venv\Scripts\python.exe'
args = ["-m", "mascotforge", "mcp"]
cwd = 'C:\path\to\mascotforge'
env = { MASCOTFORGE_URL = "http://localhost:8766" }
```

The Codex CLI and app read the same file. If you omit `cwd`, add `PYTHONPATH` to the environment table.

With `codex exec`, no person can approve an MCP call. Add `default_tools_approval_mode = "approve"` to this server block and run `codex exec -c 'approval_policy="never"'` only in an environment where you already trust the configured MascotForge tools.

### Agent Skills skill

```bash
python -m mascotforge skill
python -m mascotforge skill --dir TARGET_FOLDER
```

The command copies the skill to `.claude/skills/mascotforge/` and `.agents/skills/mascotforge/`. It preserves modified local files. Use `--force` only after the user approves replacement.

## API

| Method | Route | Description |
|---|---|---|
| GET | `/api/health` | Health, ffmpeg, and server key state |
| POST | `/api/keys/test` | Test a provider key from a header |
| GET | `/api/presets` | State presets, state limit, and cost |
| POST | `/api/character/from-prompt` | Create a base character from a prompt |
| POST | `/api/character/from-upload` | Upload a base image, 10 MB maximum |
| POST | `/api/generate` | Start state generation |
| GET | `/api/jobs/{job_id}` | Read status, states, errors, and cost |
| POST | `/api/jobs/{job_id}/retry` | Retry failed states |
| POST | `/api/jobs/{job_id}/states/{state}/regenerate` | Regenerate one state |
| POST | `/api/jobs/{job_id}/look` | Generate cursor tracking |
| GET | `/api/jobs/{job_id}/manifest.json` | Read the preview manifest |
| POST | `/api/export/{job_id}` | Build the export archive |
| GET | `/api/engines` | List code engines and settings |
| GET | `/api/engines/blob/guide` | Read the custom Blob guide |
| GET | `/api/engines/3d/guide` | Read the Wobnimo spec guide |
| POST | `/api/engines/blob/specs/check` | Check a custom Blob spec |
| POST | `/api/engines/blob/specs/preview` | Render a custom Blob preview |
| POST | `/api/engines/blob/specs/export` | Export a custom Blob |
| POST | `/api/engines/3d/specs/check` | Check a Wobnimo spec |
| POST | `/api/engines/3d/specs/preview` | Render a Wobnimo preview |
| POST | `/api/engines/3d/specs` | Save a Wobnimo spec |
| POST | `/api/engines/3d/from-image` | Start image-to-3D creation |
| GET | `/api/engines/3d/specs/{spec_id}` | Read image-to-3D status |
| GET | `/api/engines/{engine}/manifest.json` | Preview a code mascot |
| POST | `/api/engines/{engine}/export` | Export a code mascot |
| GET | `/api/exports/{filename}` | Download an export |
| GET | `/videos/{job_id}/{filename}` | Read a generated clip |
| GET | `/api/cost` | Read spending, reservations, and cap |

API errors return a clean French message. Provider and ffmpeg details stay in server logs.

## Provider models and costs

Environment variables can override the provider models:

- Text to image: `fal-ai/flux/dev` through `MASCOTFORGE_TTI_MODEL`
- Image to video: `fal-ai/kling-video/v3/standard/image-to-video` through `MASCOTFORGE_I2V_MODEL`
- Video fallback: `fal-ai/kling-video/v3/pro/image-to-video` through `MASCOTFORGE_FALLBACK_MODEL`
- Image-to-3D spec: `anthropic/claude-sonnet-5.5` through `MASCOTFORGE_SPEC_MODEL`

Pricing recorded in the project:

- Kling 3.0 standard without audio: $0.084 per second on 2026-10-30
- One three-second state: about $0.25
- Four-state mascot: about $1, plus $0.025 for a prompt-generated base image
- Cursor tracking: about $0.67 for one eight-second clip
- Image-to-3D: about $0.15 to $0.60 depending on correction passes

`MASCOTFORGE_MONTHLY_CAP_USD` sets the shared monthly cap, $50 by default. MascotForge reserves a job estimate before generation so simultaneous jobs cannot exceed the cap together.

## Export format

`POST /api/export/{job_id}` creates:

```text
mascot/
  mascot.js
  manifest.json
  videos/
  README.md
```

The V2 manifest stores the default state, alpha mode, state sources, loop behavior, and model information. Code mascot manifests also store the engine, engine source, engine configuration, and optional custom spec.

## Widget

```html
<mascot-avatar manifest="./mascot/manifest.json" label="My assistant"></mascot-avatar>
<script src="./mascot/mascot.js"></script>
```

Public methods include `play(state, { immediate })`, `wake()`, and `getState()`.

Attributes include:

- `click-state`
- `sleep-state`
- `sleep-after`
- `switch="loop-end|immediate"`
- `parallax`
- `follow-cursor`
- `label`

The widget reads V1 and V2 manifests. Common aliases let `talking` work with engines that call the state `speaking`, and `happy` work with engines that call it `celebrating`.

## Code mascots

| Style | Engine | States |
|---|---|---|
| Blob | Blob Atelier, Victoria Wu, MIT | Eight built-in shapes, six materials, custom color, eyes, cheeks, accessories, and custom states |
| 3D | Wobnimo, Pourya Akhbari, MIT | Twenty built-in characters, ten common states, and custom JSON specs |

The export includes the selected engine and its license. Code mascots make no provider request at runtime.

## 3D character from an image

1. The selected provider reads the source image. fal.ai uploads it to fal storage. Direct OpenRouter sends a base64 data URL in memory and does not place the image in fal storage.
2. A vision model writes a Wobnimo JSON spec.
3. The Wobnimo checker measures the geometry and returns exact corrections.
4. Chrome or Edge renders a preview when available. `MASCOTFORGE_BROWSER` can point to the browser executable.
5. The model compares the source with the preview and can correct the spec twice.
6. MascotForge checks every correction again and exports the validated spec.

The result interprets the source in Wobnimo's style. The checker validates geometry, while the visual comparison handles similarity.

## Cursor tracking

MascotForge generates an eight-second clip in which the head looks left, right, up, and down. The keying pipeline measures gaze direction in each frame and writes a lookup map to the manifest.

While the mascot is idle, the widget displays the frame closest to the cursor direction. Any `play()` call stops tracking. The clip loads after the first mouse movement. Tracking stays off on touch devices, with reduced motion, or when `follow-cursor="false"`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

fal.ai and OpenRouter are mocked. `tests/test_alpha.py` runs real ffmpeg against a synthetic clip. Chromium tests skip when Playwright is missing. `widget/smoke.html` provides a browser smoke test.

## Main files

- `backend/main.py`: FastAPI routes and static files
- `backend/blob.py`: custom Blob specs, checks, previews, and exports
- `backend/fal.py`: fal.ai client
- `backend/openrouter.py`: direct OpenRouter client
- `backend/alpha.py`: keying and gaze measurement
- `backend/pipeline.py`: generation jobs, fallback, retries, and recovery
- `backend/cost.py`: spending, reservations, and cap
- `backend/exporter.py`: manifest and archive generation
- `backend/engines.py`: code engines and manifests
- `backend/image3d.py`: image-to-Wobnimo pipeline
- `mascotforge/`: CLI, client, and MCP server
- `widget/mascot-avatar.js`: Web Component
- `studio/`: browser interface
- `skills/mascotforge/`: Agent Skills skill

