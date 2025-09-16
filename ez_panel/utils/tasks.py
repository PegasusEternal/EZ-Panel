"""
Safe, allowlisted task runner used by EZ-Panel.

Overview
--------
This module provides a minimal framework for executing pre-approved maintenance
tasks. Tasks are defined declaratively in YAML (see tasks/approved.yml), and each
task specifies:
  - an id, name, and description
  - a shell command template with named placeholders like {path}
  - a mode (host | docker) that decides where the command is executed
  - an optional list of parameters with regex validation rules

Important Safety Properties
---------------------------
  - Only tasks listed in YAML can be executed.
  - Every parameter is regex-validated, then shell-escaped via shlex.quote.
  - Commands are run with a configurable timeout.
  - Docker execution targets a specific container name from env (not arbitrary).

Customization Tips
------------------
  - To add tasks, edit tasks/approved.yml. Keep regexes strict (e.g., don't allow spaces
    unless necessary) and validate expected input shapes.
  - Use mode: docker for commands that must execute inside a container.
  - Set TASK_TIMEOUT and EXEC_CONTAINER_NAME environment variables to tune behavior.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import yaml  # type: ignore


# Resolve default approved tasks file path relative to this module
HERE = os.path.abspath(os.path.dirname(__file__))
DEFAULT_TASKS_PATHS = [
    os.path.abspath(os.path.join(HERE, "..", "..", "tasks", "approved.yml")),
]


@dataclass
class ParamDef:
    """Parameter schema for a task placeholder.

    - name: placeholder name used in the command template (e.g., {path})
    - pattern: regex that the provided value must match (kept conservative by default)
    - required: whether the parameter must be provided
    """

    name: str
    pattern: str = r"^[\w/\-.]+$"  # conservative default (no spaces, limited symbols)
    required: bool = True


@dataclass
class Task:
    """In-memory representation of a task loaded from YAML."""

    id: str
    name: str
    description: str
    command: str
    mode: str = "host"  # host | docker
    params: List[ParamDef] | None = None


def _load_yaml(path: str) -> Dict[str, Any]:
    """Load YAML safely from the given path. Returns an empty dict on empty files."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _discover_task_files() -> List[str]:
    """Return a list of existing task definition files to load."""
    out: List[str] = []
    for p in DEFAULT_TASKS_PATHS:
        if os.path.exists(p):
            out.append(p)
    return out


def load_tasks() -> List[Task]:
    """Load and parse tasks from YAML into Task objects.

    - Skips malformed entries gracefully.
    - First occurrence of a task id wins (later duplicates are ignored).
    """
    tasks: List[Task] = []
    for path in _discover_task_files():
        try:
            data = _load_yaml(path)
        except Exception:
            continue
        for item in data.get("tasks", []) or []:
            try:
                params = [
                    ParamDef(
                        name=p.get("name"),
                        pattern=p.get("pattern", r"^[\w/\-.]+$"),
                        required=bool(p.get("required", True)),
                    )
                    for p in (item.get("params") or [])
                    if p.get("name")
                ]
                tasks.append(
                    Task(
                        id=item["id"],
                        name=item.get("name", item["id"]),
                        description=item.get("description", ""),
                        command=item["command"],
                        mode=item.get("mode", "host"),
                        params=params or None,
                    )
                )
            except Exception:
                # Skip malformed entries without breaking the entire load
                continue
    # De-duplicate by id (first wins)
    seen: set[str] = set()
    uniq: List[Task] = []
    for t in tasks:
        if t.id not in seen:
            uniq.append(t)
            seen.add(t.id)
    return uniq

def _validate_and_render(task: Task, params: Dict[str, Any] | None) -> Tuple[bool, str]:
    """Validate provided params against the task schema and render the command.

    Returns (ok, value). If ok is True, value is the rendered command string. Otherwise
    value is a human-readable error message.
    """
    params = params or {}
    # Build allowed params map and validate names
    allowed: Dict[str, ParamDef] = {p.name: p for p in (task.params or [])}
    for k in params.keys():
        if k not in allowed:
            return False, f"Unknown parameter: {k}"
    # Validate required params
    for name, pdef in allowed.items():
        if pdef.required and name not in params:
            return False, f"Missing required parameter: {name}"
    # Prepare safe formatting map
    safe_map: Dict[str, str] = {}
    for name, pdef in allowed.items():
        val = str(params.get(name, ""))
        try:
            if not re.match(pdef.pattern, val):
                return False, f"Parameter '{name}' failed validation"
        except re.error:
            return False, f"Invalid regex for '{name}'"
        # Escape for shell usage to prevent injection
        safe_map[name] = shlex.quote(val)
    # Render command template
    try:
        rendered = task.command.format_map(safe_map)
    except KeyError as e:
        return False, f"Missing placeholder: {e}"
    except Exception as exc:
        return False, f"Format error: {exc}"
    return True, rendered


def run_task(task: Task, params: Dict[str, Any] | None = None, *, cwd: Optional[str] = None) -> Tuple[int, str]:
    """Execute a validated task and return (returncode, combined_output).

    - Commands run in a bash -lc subshell with a preceding 'cd <cwd>' for context.
    - In docker mode, the command is executed inside a specific container via docker exec.
    - Timeouts and target container are controlled by env.
    """
    # Validate and render the command template before execution
    ok, rendered = _validate_and_render(task, params)
    if not ok:
        return 2, rendered

    timeout_s = int(os.getenv("TASK_TIMEOUT", "120"))
    mode = task.mode
    cwd = cwd or ("/root" if mode == "docker" else (os.path.expanduser("~") or "/"))
    wrapped = f"cd {shlex.quote(cwd)} ; {rendered}"
    try:
        if mode == "docker":
            # Execute inside a specific container; avoid arbitrary container selection
            target_container = os.getenv("EXEC_CONTAINER_NAME", "c2panel_c2panel_1")
            proc = subprocess.run(
                ["docker", "exec", target_container, "bash", "-lc", wrapped],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        else:
            proc = subprocess.run(
                ["bash", "-lc", wrapped],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        return 124, "Task timed out"
    except Exception as exc:
        return 1, f"Task error: {exc}"
