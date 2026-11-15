# MascotForge terrain

`site/` is a static, self-contained playground for GitHub Pages. It has no build tool and makes no runtime request to a CDN or third-party service.

## Rebuild vendored files

From the repository root:

```powershell
.venv\Scripts\python.exe site\build.py
```

The script copies the checked-in Blob Atelier fork, three.js, Wobnimo, the `<mascot-avatar>` widget, MIT licenses, and gallery assets into `site/`. It also creates local manifests for Orbi and Patch. After the script finishes, an HTTP server can serve `site/` without access to the rest of the repository.

The source gallery files under `exports/` are local creation artifacts. Their vendored copies under `site/` are the public inputs used by the page. On a clean clone without those local exports, `build.py` keeps the existing vendored gallery files and still refreshes every checked-in engine and widget.

## Serve locally

```powershell
.venv\Scripts\python.exe -m http.server 4173 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:4173/`.
