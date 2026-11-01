"""Client HTTP de l'API MascotForge existante."""
from __future__ import annotations

import io
import mimetypes
import os
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlparse

import httpx

DEFAULT_URL = "http://localhost:8766"
RUNNING_STATUSES = {"queued", "running"}


class MascotForgeError(RuntimeError):
    """Erreur propre du client, sans detail reseau sensible."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MascotForgeClient:
    """Appelle le serveur MascotForge avec les cles du processus si elles existent."""

    def __init__(
        self,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 240.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("MASCOTFORGE_URL") or DEFAULT_URL).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MascotForgeError("MASCOTFORGE_URL doit etre une URL HTTP ou HTTPS valide.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise MascotForgeError("MASCOTFORGE_URL ne doit contenir ni secret, ni parametre, ni fragment.")
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> "MascotForgeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _request(self, method: str, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        headers = httpx.Headers(kwargs.pop("headers", None))
        fal_key = os.getenv("MASCOTFORGE_FAL_KEY", "").strip()
        openrouter_key = os.getenv("MASCOTFORGE_OPENROUTER_KEY", "").strip()
        if fal_key:
            headers.setdefault("X-Fal-Key", fal_key)
        if openrouter_key:
            headers.setdefault("X-OpenRouter-Key", openrouter_key)
        if headers:
            kwargs["headers"] = headers
        try:
            response = self._http.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise MascotForgeError("Le serveur MascotForge est injoignable.") from exc
        if response.is_error:
            message = f"Le serveur MascotForge a refuse la requete ({response.status_code})."
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str) and detail:
                    message = detail
            except (ValueError, AttributeError):
                pass
            raise MascotForgeError(message, response.status_code)
        return response

    def _json(self, method: str, path: str, **kwargs: object) -> dict:
        response = self._request(method, path, **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise MascotForgeError("Le serveur MascotForge a renvoye une reponse JSON invalide.") from exc
        if not isinstance(body, dict):
            raise MascotForgeError("Le serveur MascotForge a renvoye un format inattendu.")
        return body

    def styles(self) -> dict:
        return {
            "engines": self._json("GET", "/api/engines"),
            "presets": self._json("GET", "/api/presets"),
        }

    def cost(self) -> dict:
        return self._json("GET", "/api/cost")

    def export_code(self, engine: str, config: dict[str, str], out: Path) -> dict:
        exported = self._json(
            "POST", f"/api/engines/{engine}/export", json={"config": config}
        )
        return self._download_and_extract(exported, out)

    def spec_guide(self) -> str:
        body = self._json("GET", "/api/engines/3d/guide")
        guide = body.get("guide")
        if not isinstance(guide, str) or not guide:
            raise MascotForgeError("Le serveur MascotForge n'a pas fourni le guide Wobnimo.")
        return guide

    def spec_check(self, spec: dict) -> dict:
        return self._json("POST", "/api/engines/3d/specs/check", json={"spec": spec})

    def spec_preview(self, spec: dict) -> bytes:
        response = self._request("POST", "/api/engines/3d/specs/preview", json={"spec": spec})
        if response.headers.get("content-type", "").split(";", 1)[0] != "image/png":
            raise MascotForgeError("Le serveur MascotForge n'a pas renvoye une planche PNG.")
        return response.content

    def spec_save(self, spec: dict) -> dict:
        return self._json("POST", "/api/engines/3d/specs", json={"spec": spec})

    def spec_export(self, spec: dict, out: Path) -> dict:
        saved = self.spec_save(spec)
        exported = self.export_creation(saved["spec_id"], out)
        return {**saved, **exported}

    def start_image3d(self, image: Path) -> dict:
        image = self._require_image(image)
        mime = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        with image.open("rb") as handle:
            return self._json(
                "POST",
                "/api/engines/3d/from-image",
                files={"file": (image.name, handle, mime)},
            )

    def image3d_status(self, spec_id: str) -> dict:
        return self._json("GET", f"/api/engines/3d/specs/{spec_id}")

    def wait_image3d(
        self,
        spec_id: str,
        poll_interval: float = 1.0,
        timeout: float = 900.0,
        on_update: Callable[[dict], None] | None = None,
    ) -> dict:
        return self._wait(
            lambda: self.image3d_status(spec_id), poll_interval, timeout, on_update
        )

    def start_video(
        self,
        usage: str,
        image: Path | None = None,
        prompt: str | None = None,
    ) -> dict:
        if (image is None) == (prompt is None):
            raise MascotForgeError("Donnez soit une image, soit un prompt, mais pas les deux.")
        if image is not None:
            image = self._require_image(image)
            mime = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
            with image.open("rb") as handle:
                character = self._json(
                    "POST",
                    "/api/character/from-upload",
                    files={"file": (image.name, handle, mime)},
                )
        else:
            clean_prompt = (prompt or "").strip()
            if not clean_prompt:
                raise MascotForgeError("Le prompt ne peut pas etre vide.")
            character = self._json(
                "POST", "/api/character/from-prompt", json={"prompt": clean_prompt}
            )
        generated = self._json(
            "POST",
            "/api/generate",
            json={"character_id": character["character_id"], "usage": usage},
        )
        return {**generated, "character_id": character["character_id"]}

    def video_status(self, job_id: str) -> dict:
        return self._json("GET", f"/api/jobs/{job_id}")

    def wait_video(
        self,
        job_id: str,
        poll_interval: float = 1.0,
        timeout: float = 1800.0,
        on_update: Callable[[dict], None] | None = None,
    ) -> dict:
        return self._wait(lambda: self.video_status(job_id), poll_interval, timeout, on_update)

    def status(self, creation_id: str) -> dict:
        try:
            return {"type": "video", **self.video_status(creation_id)}
        except MascotForgeError as exc:
            if exc.status_code != 404:
                raise
        return {"type": "image3d", **self.image3d_status(creation_id)}

    def export_creation(self, creation_id: str, out: Path) -> dict:
        try:
            exported = self._json("POST", f"/api/export/{creation_id}")
            creation_type = "video"
        except MascotForgeError as exc:
            if exc.status_code != 404:
                raise
            exported = self._json(
                "POST", "/api/engines/3d/export", json={"config": {"spec": creation_id}}
            )
            creation_type = "image3d"
        return {"type": creation_type, **self._download_and_extract(exported, out)}

    def _wait(
        self,
        fetch: Callable[[], dict],
        poll_interval: float,
        timeout: float,
        on_update: Callable[[dict], None] | None,
    ) -> dict:
        deadline = time.monotonic() + timeout
        previous: str | None = None
        while True:
            current = fetch()
            status = str(current.get("status", ""))
            if on_update is not None and status != previous:
                on_update(current)
            previous = status
            if status not in RUNNING_STATUSES:
                if status != "done":
                    error = current.get("error")
                    message = f"La creation a echoue (statut {status or 'inconnu'})."
                    if isinstance(error, str) and error:
                        message = error
                    raise MascotForgeError(message)
                return current
            if time.monotonic() >= deadline:
                raise MascotForgeError("Le delai de suivi de la creation est depasse.")
            time.sleep(poll_interval)

    def _download_and_extract(self, exported: dict, out: Path) -> dict:
        download_url = exported.get("download_url")
        if not isinstance(download_url, str) or not download_url:
            raise MascotForgeError("L'API n'a pas fourni de lien de telechargement.")
        parsed = urlparse(download_url)
        if parsed.scheme or parsed.netloc:
            expected = urlparse(self.base_url)
            if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
                raise MascotForgeError("Le lien d'export pointe vers un autre serveur.")
        response = self._request("GET", download_url)
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                self._safe_extract(archive, out)
                files = [name for name in archive.namelist() if not name.endswith("/")]
        except zipfile.BadZipFile as exc:
            raise MascotForgeError("L'export telecharge n'est pas un fichier zip valide.") from exc
        return {
            "filename": exported.get("filename"),
            "out": str(out.resolve()),
            "files": files,
        }

    @staticmethod
    def _safe_extract(archive: zipfile.ZipFile, out: Path) -> None:
        root = out.resolve()
        for member in archive.infolist():
            name = member.filename
            path = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or path.is_absolute()
                or ".." in path.parts
                or (path.parts and ":" in path.parts[0])
            ):
                raise MascotForgeError("Le zip contient un chemin de fichier dangereux.")
            target = (root / Path(*path.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise MascotForgeError("Le zip tente d'ecrire hors du dossier de sortie.") from exc
        archive.extractall(root)

    @staticmethod
    def _require_image(path: Path) -> Path:
        image = Path(path)
        if not image.is_file():
            raise MascotForgeError(f"Image introuvable : {image}")
        return image
