"""Tests for the code execution sandbox (real subprocesses)."""

import pytest

from app.services.code_sandbox import SubprocessSandbox, resource


@pytest.fixture
def sandbox() -> SubprocessSandbox:
    return SubprocessSandbox()


async def test_runs_and_captures_stdout(sandbox):
    res = await sandbox.run("print('hello world')")
    assert res.ok and res.exit_code == 0
    assert "hello world" in res.stdout
    assert res.timed_out is False


async def test_runtime_exception_is_nonzero(sandbox):
    res = await sandbox.run("raise ValueError('boom')")
    assert not res.ok and res.exit_code != 0
    assert "ValueError" in res.stderr and "boom" in res.stderr


async def test_syntax_error_reported(sandbox):
    res = await sandbox.run("def (:\n  pass")
    assert not res.ok
    assert "SyntaxError" in res.stderr


async def test_timeout_is_enforced(sandbox):
    res = await sandbox.run("import time; time.sleep(3)", timeout=1)
    assert res.timed_out is True and not res.ok


@pytest.mark.skipif(resource is None, reason="POSIX resource limits unavailable")
async def test_memory_limit_is_enforced(sandbox):
    # Allocate far more than the configured address-space limit.
    res = await sandbox.run("x = bytearray(400 * 1024 * 1024)\nprint(len(x))")
    assert not res.ok  # killed or MemoryError, never a clean success


async def test_multiline_stdout(sandbox):
    res = await sandbox.run("for i in range(3):\n    print('line', i)")
    assert res.ok
    assert "line 0" in res.stdout and "line 2" in res.stdout
