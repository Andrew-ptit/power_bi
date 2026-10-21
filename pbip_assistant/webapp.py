"""Loopback-only web UI for profiling raw Excel and CSV sources."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
from threading import RLock
from typing import Any
from urllib.parse import unquote, urlsplit
import webbrowser

from .errors import InputError
from .source_workflow import profile_sources_only


MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
SUPPORTED_EXTENSIONS = frozenset({".xlsx", ".csv"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
STATIC_ROOT = Path(__file__).with_name("web")


@dataclass(frozen=True)
class StoredFile:
    id: str
    name: str
    path: Path
    size: int
    sha256: str
    kind: str

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("path")
        return result


class UploadStore:
    """Temporary uploaded-copy store for one local server process."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="pbip-source-ui-") if root is None else None
        self.root = Path(root if root is not None else self._temporary.name).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, StoredFile] = {}
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._files.clear()
        if self._temporary is not None:
            self._temporary.cleanup()

    def list_files(self) -> list[dict[str, Any]]:
        with self._lock:
            return [item.public() for item in self._files.values()]

    def add(self, filename: str, payload: bytes) -> dict[str, Any]:
        if not filename or "\x00" in filename:
            raise InputError("INVALID_FILENAME", filename, "File name is missing or invalid")
        safe_name = Path(filename).name
        if safe_name != filename or safe_name in {"", ".", ".."}:
            raise InputError(
                "INVALID_FILENAME",
                filename,
                "Only a plain file name without folders is accepted",
            )
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise InputError(
                "UNSUPPORTED_SOURCE",
                safe_name,
                "Only .xlsx and .csv files are supported",
            )
        if not payload:
            raise InputError("EMPTY_UPLOAD", safe_name, "The selected file is empty")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise InputError(
                "UPLOAD_LIMIT",
                safe_name,
                f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit",
            )
        with self._lock:
            total = sum(item.size for item in self._files.values())
            if total + len(payload) > MAX_TOTAL_BYTES:
                raise InputError(
                    "SESSION_LIMIT",
                    safe_name,
                    f"Session exceeds the {MAX_TOTAL_BYTES // (1024 * 1024)} MiB limit",
                )
            file_id = secrets.token_urlsafe(12)
            stored_path = self.root / f"{file_id}{suffix}"
            stored_path.write_bytes(payload)
            item = StoredFile(
                id=file_id,
                name=safe_name,
                path=stored_path,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                kind=suffix.removeprefix("."),
            )
            self._files[file_id] = item
            return item.public()

    def remove(self, file_id: str) -> bool:
        with self._lock:
            item = self._files.pop(file_id, None)
            if item is None:
                return False
            item.path.unlink(missing_ok=True)
            return True

    def reset(self) -> None:
        with self._lock:
            items = list(self._files.values())
            self._files.clear()
        for item in items:
            item.path.unlink(missing_ok=True)

    def profile(self, request: dict[str, Any]) -> dict[str, Any]:
        requested = request.get("files")
        if not isinstance(requested, list) or not requested:
            raise InputError("NO_SOURCES", "", "Choose at least one uploaded file")
        preview_limit = request.get("preview_limit", 20)
        if not isinstance(preview_limit, int):
            raise InputError("PREVIEW_LIMIT", "", "preview_limit must be an integer")

        with self._lock:
            selected: list[StoredFile] = []
            options_by_path: dict[str, dict[str, Any]] = {}
            for entry in requested:
                if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                    raise InputError("INVALID_REQUEST", "", "Each file needs a valid id")
                item = self._files.get(entry["id"])
                if item is None:
                    raise InputError("FILE_NOT_FOUND", entry["id"], "Uploaded file is no longer available")
                options = entry.get("options") or {}
                if not isinstance(options, dict):
                    raise InputError("INVALID_OPTIONS", item.name, "File options must be an object")
                selected.append(item)
                options_by_path[str(item.path)] = self._validated_options(item, options)

        result = profile_sources_only(
            [item.path for item in selected],
            source_options=options_by_path,
            include_preview=True,
            preview_limit=preview_limit,
        )
        by_path = {str(item.path.resolve()): item for item in selected}
        self._replace_private_paths(result, by_path)
        return result

    @staticmethod
    def _validated_options(item: StoredFile, options: dict[str, Any]) -> dict[str, Any]:
        if item.kind == "csv":
            allowed = {"encoding", "delimiter", "header_row"}
            unknown = set(options) - allowed
            if unknown:
                raise InputError("INVALID_OPTIONS", item.name, f"Unknown CSV option(s): {', '.join(sorted(unknown))}")
            header_row = options.get("header_row", 1)
            if not isinstance(header_row, int) or isinstance(header_row, bool):
                raise InputError("CSV_HEADER", item.name, "header_row must be an integer")
            return {
                **({"encoding": options["encoding"]} if options.get("encoding") else {}),
                **({"delimiter": options["delimiter"]} if options.get("delimiter") else {}),
                "header_row": header_row,
            }
        allowed = {"sheet_names", "table_name"}
        unknown = set(options) - allowed
        if unknown:
            raise InputError("INVALID_OPTIONS", item.name, f"Unknown XLSX option(s): {', '.join(sorted(unknown))}")
        sheet_names = options.get("sheet_names")
        if sheet_names is not None and (
            not isinstance(sheet_names, list)
            or not all(isinstance(value, str) and value for value in sheet_names)
        ):
            raise InputError("INVALID_OPTIONS", item.name, "sheet_names must be a list of names")
        table_name = options.get("table_name")
        if table_name is not None and not isinstance(table_name, str):
            raise InputError("INVALID_OPTIONS", item.name, "table_name must be text")
        return {
            **({"sheet_names": sheet_names} if sheet_names else {}),
            **({"table_name": table_name} if table_name else {}),
        }

    @staticmethod
    def _replace_private_paths(result: dict[str, Any], by_path: dict[str, StoredFile]) -> None:
        def public_path(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            try:
                resolved = str(Path(value).resolve())
            except OSError:
                return value
            item = by_path.get(resolved)
            return item.name if item else value

        for key in ("workbooks", "csv_files"):
            for profile in result.get(key, []):
                item = by_path.get(str(Path(profile.get("path", "")).resolve()))
                if item:
                    profile["path"] = item.name
                    profile["file_id"] = item.id
                    profile["source_sha256"] = item.sha256
                    profile["source_size"] = item.size
        for error in result.get("errors", []):
            error["path"] = public_path(error.get("path", ""))
        comparison = result.get("schema_comparison", {})
        if comparison.get("baseline"):
            comparison["baseline"]["path"] = public_path(comparison["baseline"].get("path"))
        for item in comparison.get("comparisons", []):
            item["path"] = public_path(item.get("path"))


class LocalApp:
    def __init__(self, store: UploadStore | None = None) -> None:
        self.store = store or UploadStore()
        self.token = secrets.token_urlsafe(24)


class LocalRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PBIPSourceUI/0.1"

    def __init__(self, *args: Any, app: LocalApp, **kwargs: Any) -> None:
        self.app = app
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        # Never log request bodies, file names, query strings, or raw cells.
        method = self.command if isinstance(self.command, str) else "INVALID"
        request_path = urlsplit(self.path).path if isinstance(self.path, str) else "-"
        print(f"[local-ui] {method} {request_path}")

    def do_GET(self) -> None:
        if not self._request_host_allowed():
            return
        path = urlsplit(self.path).path
        if path == "/api/bootstrap":
            self._json(HTTPStatus.OK, {
                "token": self.app.token,
                "files": self.app.store.list_files(),
                "limits": {
                    "file_bytes": MAX_UPLOAD_BYTES,
                    "session_bytes": MAX_TOTAL_BYTES,
                    "preview_rows": 50,
                },
                "capabilities": {
                    "xlsx": True,
                    "csv": True,
                    "pbip": False,
                    "ai": False,
                    "write_source": False,
                },
            })
            return
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok", "scope": "source_only"})
            return
        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        target = static_files.get(path)
        if target is None:
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Page not found")
            return
        file_path = STATIC_ROOT / target[0]
        if not file_path.is_file():
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "ASSET_MISSING", "Local UI asset is missing")
            return
        self._bytes(HTTPStatus.OK, file_path.read_bytes(), target[1])

    def do_POST(self) -> None:
        if not self._mutation_allowed():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/files":
                filename = unquote(self.headers.get("X-File-Name", ""))
                payload = self._read_body(MAX_UPLOAD_BYTES)
                self._json(HTTPStatus.CREATED, {"file": self.app.store.add(filename, payload)})
                return
            if path == "/api/profile":
                request = self._read_json()
                self._json(HTTPStatus.OK, self.app.store.profile(request))
                return
            if path == "/api/reset":
                self._read_body(MAX_JSON_BYTES)
                self.app.store.reset()
                self._json(HTTPStatus.OK, {"files": []})
                return
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")
        except InputError as exc:
            self._error(HTTPStatus.BAD_REQUEST, exc.code, exc.detail, path=exc.path)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", str(exc))
        except OSError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "IO_ERROR", "Local file operation failed")

    def do_DELETE(self) -> None:
        if not self._mutation_allowed():
            return
        path = urlsplit(self.path).path
        prefix = "/api/files/"
        if not path.startswith(prefix):
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")
            return
        file_id = path[len(prefix):]
        if not file_id or "/" in file_id:
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", "Invalid file id")
            return
        if not self.app.store.remove(file_id):
            self._error(HTTPStatus.NOT_FOUND, "FILE_NOT_FOUND", "Uploaded file is no longer available")
            return
        self._json(HTTPStatus.OK, {"removed": file_id})

    def _request_host_allowed(self) -> bool:
        host_header = self.headers.get("Host", "")
        try:
            hostname = urlsplit(f"//{host_header}").hostname
        except ValueError:
            hostname = None
        if hostname not in LOOPBACK_HOSTS:
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "HOST_BLOCKED", "Only loopback hosts are accepted")
            return False
        return True

    def _mutation_allowed(self) -> bool:
        if not self._request_host_allowed():
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                parsed = None
            if parsed is None or parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
                self._error(HTTPStatus.FORBIDDEN, "ORIGIN_BLOCKED", "Cross-origin request blocked")
                return False
        if not secrets.compare_digest(self.headers.get("X-Local-Token", ""), self.app.token):
            self._error(HTTPStatus.FORBIDDEN, "TOKEN_REQUIRED", "Local session token is missing or invalid")
            return False
        return True

    def _read_body(self, maximum: int) -> bytes:
        value = self.headers.get("Content-Length")
        if value is None:
            raise ValueError("Content-Length is required")
        length = int(value)
        if length < 0 or length > maximum:
            raise InputError("REQUEST_LIMIT", "", f"Request exceeds {maximum} bytes")
        payload = self.rfile.read(length)
        if len(payload) != length:
            raise ValueError("Request body ended early")
        return payload

    def _read_json(self) -> dict[str, Any]:
        payload = self._read_body(MAX_JSON_BYTES)
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _bytes(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        self._bytes(
            status,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _error(self, status: HTTPStatus, code: str, detail: str, *, path: str = "") -> None:
        # Errors may be raised before a request body is consumed. Closing keeps
        # those bytes from being interpreted as another HTTP/1.1 request.
        self.close_connection = True
        self._json(status, {"error": {"code": code, "detail": detail, "path": path}})


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    store: UploadStore | None = None,
) -> LocalThreadingHTTPServer:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("The raw-data UI may bind only to a loopback address")
    app = LocalApp(store)

    def handler(*args: Any, **kwargs: Any) -> LocalRequestHandler:
        return LocalRequestHandler(*args, app=app, **kwargs)

    server = LocalThreadingHTTPServer((host, port), handler)
    server.app = app  # type: ignore[attr-defined]
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Local raw-data profiling UI")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "::1"])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local UI in the default browser")
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    address, port = server.server_address[:2]
    display_host = f"[{address}]" if ":" in address else address
    url = f"http://{display_host}:{port}/"
    print(f"Raw-data UI: {url}")
    print("Local-only, read-only source profiling. Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local UI.")
    finally:
        server.shutdown()
        server.server_close()
        server.app.store.close()  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
