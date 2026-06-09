"""Filesystem service: the safe, sandboxed layer that does the real work.

Every operation is confined to a single workspace root. The one rule that makes
this safe is `_resolve`: any caller-supplied path is joined to the root,
canonicalized (which collapses `..` and resolves symlinks), and then checked to
still be inside the root. An absolute path, a `../../etc/passwd`, or a symlink
that points outside the workspace all fail that check and raise before any IO
happens. This is pure, synchronous, and has no LLM dependency, so it is fully
unit-testable.
"""

import fnmatch
import os
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class FileServiceError(Exception):
    """Base error; the tool pipeline turns these into error envelopes."""


class PathNotAllowed(FileServiceError):
    pass


class NotFound(FileServiceError):
    pass


class AlreadyExists(FileServiceError):
    pass


class TooLarge(FileServiceError):
    pass


class FileService:
    def __init__(self, root: str | Path | None = None) -> None:
        s = get_settings()
        self.root = Path(root or s.file_workspace_root).resolve()
        self.max_read = s.file_max_read_bytes
        self.max_write = s.file_max_write_bytes
        self.max_results = s.file_search_max_results

    # --- the safety primitive ---------------------------------------------

    def _resolve(self, path: str) -> Path:
        if path is None or path == "":
            raise PathNotAllowed("empty path")
        candidate = (self.root / path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise PathNotAllowed(f"path escapes the workspace: {path}")
        return candidate

    def _rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    # --- operations -------------------------------------------------------

    def create(self, path: str, content: str = "", overwrite: bool = False) -> dict:
        target = self._resolve(path)
        if target.exists() and not overwrite:
            raise AlreadyExists(f"file exists: {path} (set overwrite=true to replace)")
        data = content.encode("utf-8")
        if len(data) > self.max_write:
            raise TooLarge(f"content exceeds {self.max_write} bytes")
        self.root.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": self._rel(target), "bytes": len(data), "overwritten": target.exists()}

    def read(self, path: str) -> dict:
        target = self._resolve(path)
        if not target.exists():
            raise NotFound(f"no such file: {path}")
        if target.is_dir():
            raise PathNotAllowed(f"path is a directory: {path}")
        size = target.stat().st_size
        if size > self.max_read:
            raise TooLarge(f"file is {size} bytes; limit is {self.max_read}")
        raw = target.read_bytes()
        binary = b"\x00" in raw
        content = "" if binary else raw.decode("utf-8", errors="replace")
        return {"path": self._rel(target), "bytes": size,
                "binary": binary, "content": content}

    def delete(self, path: str) -> dict:
        target = self._resolve(path)
        if not target.exists():
            raise NotFound(f"no such file: {path}")
        if target.is_dir():
            raise PathNotAllowed(f"refusing to delete a directory: {path}")
        target.unlink()
        return {"deleted": self._rel(target)}

    def rename(self, src: str, dst: str, overwrite: bool = False) -> dict:
        source = self._resolve(src)
        dest = self._resolve(dst)
        if not source.exists():
            raise NotFound(f"no such file: {src}")
        if dest.exists() and not overwrite:
            raise AlreadyExists(f"destination exists: {dst}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return {"from": self._rel(source), "to": self._rel(dest)}

    def search(self, query: str = "", glob: str = "*",
               search_content: bool = False, path: str = ".") -> dict:
        base = self._resolve(path) if path not in ("", ".") else self.root
        if not base.exists():
            return {"matches": [], "count": 0}

        q = query.lower()
        matches: list[dict] = []
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if not fnmatch.fnmatch(name, glob):
                    continue
                full = Path(dirpath) / name
                name_hit = q in name.lower() if q else True
                snippet = None
                if search_content and q and not name_hit:
                    snippet = self._grep(full, q)
                if name_hit or snippet is not None:
                    matches.append({"path": self._rel(full),
                                    "name": name,
                                    "size": full.stat().st_size,
                                    "snippet": snippet})
                if len(matches) >= self.max_results:
                    return {"matches": matches, "count": len(matches), "truncated": True}
        return {"matches": matches, "count": len(matches)}

    def _grep(self, full: Path, q: str) -> str | None:
        try:
            if full.stat().st_size > self.max_read:
                return None
            text = full.read_text("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - unreadable file is simply not a match
            return None
        idx = text.lower().find(q)
        if idx < 0:
            return None
        start = max(0, idx - 30)
        return text[start: idx + len(q) + 30].replace("\n", " ")
