"""Code execution sandbox.

Running model-generated code is one of the two genuinely dangerous capabilities
in the system, so execution is hidden behind an interface (CodeSandbox) with a
single, swappable implementation.

The default, SubprocessSandbox, gives PROCESS-LEVEL isolation:
  - a fresh temp working directory, removed after the run
  - Python launched in isolated mode (-I): ignores env vars, user site-packages
  - POSIX resource limits applied in the child before exec: CPU time (catches
    busy loops via SIGXCPU), address space (catches memory bombs), file size,
    and process count (blunts fork bombs)
  - its own session/process group, so a wall-clock timeout can kill the whole
    tree
  - a minimal environment and closed stdin

This is suitable for development and for low-trust-but-not-adversarial code. It
is NOT a substitute for a real security boundary: a process sandbox cannot, on
its own, block network access or contain a kernel exploit. In production, swap
in a sandbox backed by a disposable container or microVM (Docker, gVisor,
Firecracker) by implementing CodeSandbox. The rest of the system does not change.
"""

import asyncio
import os
import shutil
import signal
import sys
import tempfile
from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

try:
    import resource  # POSIX only
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore

log = get_logger(__name__)


class ExecutionResult(BaseModel):
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: float


class CodeSandbox(ABC):
    @abstractmethod
    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult: ...


def _limit_fn(cpu: int, mem_bytes: int, fsize: int, nproc: int):
    """Returned function runs in the child after fork, before exec."""

    def apply() -> None:
        os.setsid()  # new session so the whole group can be killed on timeout
        if resource is None:
            return
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
        except (ValueError, OSError):  # not settable everywhere
            pass

    return apply


class SubprocessSandbox(CodeSandbox):
    def __init__(self) -> None:
        s = get_settings()
        self.cpu_seconds = s.code_exec_cpu_seconds
        self.mem_bytes = s.code_exec_memory_mb * 1024 * 1024
        self.timeout = s.code_exec_timeout_seconds
        self.fsize = s.code_exec_fsize_bytes
        self.nproc = s.code_exec_nproc
        self.max_output = s.code_exec_max_output_bytes

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        wall = timeout or self.timeout
        workdir = tempfile.mkdtemp(prefix="jarvis-exec-")
        script = os.path.join(workdir, "main.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(code)

        loop = asyncio.get_running_loop()
        start = loop.time()
        preexec = _limit_fn(self.cpu_seconds, self.mem_bytes, self.fsize, self.nproc) \
            if sys.platform != "win32" else None

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", script,
                cwd=workdir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "HOME": workdir, "TMPDIR": workdir},
                preexec_fn=preexec,
            )
            timed_out = False
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=wall)
            except asyncio.TimeoutError:
                timed_out = True
                self._kill(proc)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
                out, err = b"", b"execution timed out"

            duration_ms = round((loop.time() - start) * 1000, 2)
            exit_code = proc.returncode
            result = ExecutionResult(
                ok=(not timed_out and exit_code == 0),
                exit_code=exit_code,
                stdout=self._clip(out),
                stderr=self._clip(err),
                timed_out=timed_out,
                duration_ms=duration_ms,
            )
            log.info("code.execute", ok=result.ok, exit_code=exit_code,
                     timed_out=timed_out, duration_ms=duration_ms)
            return result
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _kill(proc) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    def _clip(self, raw: bytes) -> str:
        text = raw[: self.max_output].decode("utf-8", errors="replace")
        if len(raw) > self.max_output:
            text += "\n...[output truncated]"
        return text


def get_sandbox() -> CodeSandbox:
    return SubprocessSandbox()
