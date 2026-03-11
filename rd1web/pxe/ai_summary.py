"""
AI summary generation for RMA/GB log folders via OpenClaw agent call.
Used by rma_logs views.
"""
import json
import os
import random
import re
import time
from collections import deque
from urllib import error as urllib_error
from urllib import request as urllib_request

# Config (can be overridden from local_config later)
AI_SUMMARY_OPENCLAW_HOST = ""
AI_SUMMARY_OPENCLAW_TOKEN = ""
AI_SUMMARY_OPENCLAW_MODEL = "openclaw"
AI_SUMMARY_OPENCLAW_AGENT_ID = "main"
AI_SUMMARY_MAX_FILE_SIZE_MB = 200
AI_SUMMARY_MAX_ERROR_LINES = 200
AI_SUMMARY_MAX_FILES_TO_LIST = 400
AI_SUMMARY_REQUEST_TIMEOUT_SEC = 120.0
AI_SUMMARY_MAX_CONTEXT_CHARS = 360000   # ~90k tokens context budget
AI_SUMMARY_MAX_READ_CHARS = 18000       # max chars returned per file (context budget / 20)
AI_SUMMARY_MAX_RETRIES = 3
AI_SUMMARY_RETRY_BACKOFF_BASE_SEC = 1.0
AI_SUMMARY_ERROR_REGEX = re.compile(r"error|fail|fatal|exception|traceback", re.IGNORECASE)


def resolve_openclaw_settings() -> tuple[str, str]:
    """
    Resolve OpenClaw host/token from local_config while preserving proxy behavior.
    If B31 is enabled and AI_PROXY is set, host is overridden by AI_PROXY.
    """
    host = ""
    token = ""
    try:
        from . import local_config as _local_config

        local_host = getattr(_local_config, "openclaw", "")
        local_token = getattr(_local_config, "openclaw_token", "")
        if isinstance(local_host, str):
            host = local_host.strip()
        if isinstance(local_token, str):
            token = local_token.strip()

        b31 = getattr(_local_config, "B31", False)
        ai_proxy = getattr(_local_config, "AI_PROXY", None)
        if b31 and ai_proxy and isinstance(ai_proxy, str):
            raw = ai_proxy.strip().lstrip("http://").lstrip("https://").rstrip("/")
            if raw:
                host = raw
    except ImportError:
        pass
    return host, token


AI_SUMMARY_OPENCLAW_HOST, AI_SUMMARY_OPENCLAW_TOKEN = resolve_openclaw_settings()

AI_SUMMARY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files_in_folder",
            "description": "List files in the given folder path. Use recursive=True to include all files in subfolders (paths returned relative to folder).",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Absolute or relative path to the folder",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, list all files in subfolders with relative paths (e.g. subdir/file.txt).",
                        "default": False,
                    }
                },
                "required": ["folder_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_content",
            "description": "Read important log lines (errors, failures, exceptions) from a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file",
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        },
    },
]

# Stage 2 only: model must call this to submit the final report (avoids empty message.content from vLLM).
AI_SUMMARY_STAGE2_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "write_report",
            "description": "Submit the final markdown report. Call this once with the complete report content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "markdown_report": {
                        "type": "string",
                        "description": "The complete markdown report content to save.",
                    }
                },
                "required": ["markdown_report"],
                "additionalProperties": False,
            },
        },
    },
]


def _list_files_in_folder(folder_path: str, recursive: bool = False):
    if not os.path.isdir(folder_path):
        return []
    if not recursive:
        file_names = []
        for entry in os.listdir(folder_path):
            entry_path = os.path.join(folder_path, entry)
            if os.path.isfile(entry_path):
                file_names.append(entry)
        file_names.sort()
        return file_names[:AI_SUMMARY_MAX_FILES_TO_LIST]
    # Recursive: collect relative paths (e.g. subdir/file.txt)
    rel_paths = []
    folder_path = os.path.abspath(folder_path)
    for root, _dirs, files in os.walk(folder_path):
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = os.path.relpath(full, folder_path)
            rel_paths.append(rel)
            if len(rel_paths) >= AI_SUMMARY_MAX_FILES_TO_LIST:
                return rel_paths
    return rel_paths


def _read_file_content(file_path: str) -> str:
    if not os.path.isfile(file_path):
        return f"Error: {file_path} is not a valid file."
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > AI_SUMMARY_MAX_FILE_SIZE_MB:
        return (
            f"Skipped {os.path.basename(file_path)}: File too large "
            f"({file_size_mb:.1f} MB > {AI_SUMMARY_MAX_FILE_SIZE_MB} MB)."
        )
    important_lines = deque(maxlen=AI_SUMMARY_MAX_ERROR_LINES)
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if AI_SUMMARY_ERROR_REGEX.search(line):
                    important_lines.append(line.rstrip())
    except Exception as exc:
        return f"Error reading file {os.path.basename(file_path)}: {type(exc).__name__}: {exc}"
    if not important_lines:
        return f"No critical errors found in {os.path.basename(file_path)}."
    out = "\n".join(important_lines)
    if len(out) > AI_SUMMARY_MAX_READ_CHARS:
        total_lines = len(important_lines)
        out = out[:AI_SUMMARY_MAX_READ_CHARS] + f"\n... [truncated, total {total_lines} lines]"
    return out


def _tool_list_files(allowed_base: str, folder_path_arg: str, recursive: bool = False):
    """Tool implementation: list files. Path must be under allowed_base."""
    # Resolve relative paths against allowed_base so "subdir" means allowed_base/subdir
    if not os.path.isabs(folder_path_arg):
        full = os.path.normpath(os.path.join(allowed_base, folder_path_arg))
    else:
        full = folder_path_arg
    full = os.path.abspath(full)
    if not full.startswith(allowed_base) or not os.path.isdir(full):
        return f"Error: {folder_path_arg} is not a valid directory under the scan folder."
    return _list_files_in_folder(full, recursive=recursive)


def _tool_read_file(allowed_base: str, file_path_arg: str):
    """Tool implementation: read file content. Path must be under allowed_base."""
    # Resolve relative paths (e.g. subdir/file.txt) against allowed_base
    if not os.path.isabs(file_path_arg):
        full = os.path.normpath(os.path.join(allowed_base, file_path_arg))
    else:
        full = file_path_arg
    full = os.path.abspath(full)
    if not full.startswith(allowed_base):
        return f"Error: {file_path_arg} is not under the scan folder."
    return _read_file_content(full)


def _read_gpu_model_from_sys_info(allowed_base: str):
    """Read GPU model from first line of sys_info.txt (GPU_Model: xxx). Returns None if missing."""
    path = os.path.join(allowed_base, "sys_info.txt")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
        first_line = first_line.strip()
        if ":" in first_line:
            key, value = first_line.split(":", 1)
            if key.strip() == "GPU_Model":
                return value.strip() or None
    except Exception:
        pass
    return None


def _parse_test_status_most_recent(allowed_base: str):
    """
    Parse test_status.txt: last occurrence per test name wins (most recent run).
    Returns a string like "TestA: PASSED, TestB: FAILED" or None if file missing/empty.
    """
    path = os.path.join(allowed_base, "test_status.txt")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return None
    raw_tests = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                test_name = parts[0].strip()
                status = parts[1].strip().upper()
                raw_tests[test_name] = status
        elif " " in line:
            parts = line.split(None, 1)
            if len(parts) >= 2:
                test_name = parts[0].strip()
                status = parts[1].strip().upper()
                raw_tests[test_name] = status
        else:
            raw_tests["Overall"] = line.upper()
    if not raw_tests:
        return None
    return ", ".join(f"{k}: {v}" for k, v in raw_tests.items())


AI_SUMMARY_STAGE2_SYSTEM_PROMPT = """
You are a senior datacenter GPU and server reliability engineer.

GOALS
- Summarize the logs clearly.
- Hypothesize likely root causes.
- Do NOT include an action plan.
- Do NOT include a Note section.


LOGIC RULES


1. Test Results:
- If a test appears multiple times,
    only consider the most recent result.

2. MI3XX ADDC Analyzer:
- Apply ONLY if GPU model starts with MI3XX.
- Count failed OAM modules ONLY when a named
    fatal error entry exists (oam: X).
- Never assume 8 modules unless 8 named entries exist.
- State exact confirmed count.
- Include error category and occurrence count.
- If not MI3XX, skip entirely and do not mention.

3. Fail Diagnostic Test:
- Skip:
    SyslogErrorCheck
    KernLogErrorCheck
    DmesgLogErrorCheck
    SyslogAERCheck
    KernLogAERCheck
    DmesgLogAERCheck
- Do not mention them.

4. Failed GPU / OAM serial numbers:
- If the findings mention any failed GPU or OAM serial numbers (SN),
  include them in the report in a dedicated subsection (e.g. "Failed GPU/OAM serial numbers").
- List each SN clearly; do not omit them when summarizing failures.

FORMATTING RULES

- Use clean, professional markdown.
- Use horizontal rules (---) between major sections.
- Use bullet or numbered lists for clarity.
- Keep lines roughly 60–75 characters.
- Make the report easy to scan.
"""


AI_ANALYZER_SYSTEM_PROMPT = """
You are a senior datacenter GPU and server reliability engineer.

TASK
- Analyze the provided log URL and produce a concise markdown report.
- Focus on key failures, likely root causes, and supporting evidence.
- Include actionable recommendations and a brief confidence level.

FORMAT
- Use clean, professional markdown.
- Use section headers and bullet points for readability.
- Keep the report concise and easy to scan.
"""


def _call_openclaw_markdown(
    user_content: str,
    system_prompt: str,
    fallback_text: str,
) -> str:
    host = AI_SUMMARY_OPENCLAW_HOST.strip()
    token = AI_SUMMARY_OPENCLAW_TOKEN.strip()
    if not host:
        raise ValueError("Missing OpenClaw host. Set `openclaw` in local_config.py.")
    if not token:
        raise ValueError("Missing OpenClaw token. Set `openclaw_token` in local_config.py.")

    raw_host = host.lstrip("http://").lstrip("https://").rstrip("/")
    endpoint = f"http://{raw_host}/v1/chat/completions"
    request_payload = {
        "model": AI_SUMMARY_OPENCLAW_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_content},
        ],
    }

    last_exc = None
    for attempt in range(1, AI_SUMMARY_MAX_RETRIES + 1):
        try:
            body = json.dumps(request_payload).encode("utf-8")
            req = urllib_request.Request(
                endpoint,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "x-openclaw-agent-id": AI_SUMMARY_OPENCLAW_AGENT_ID,
                },
            )
            with urllib_request.urlopen(req, timeout=AI_SUMMARY_REQUEST_TIMEOUT_SEC) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw) if raw else {}
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )
            content = (content or "").strip()
            if content:
                return content
            break
        except urllib_error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:500]
            except Exception:
                detail = str(exc)
            last_exc = RuntimeError(
                f"OpenClaw request failed ({exc.code}): {detail or exc.reason}"
            )
        except urllib_error.URLError as exc:
            last_exc = RuntimeError(f"OpenClaw connection failed: {exc.reason}")
        except Exception as exc:
            last_exc = exc

        if attempt < AI_SUMMARY_MAX_RETRIES:
            jitter = random.uniform(0.0, 0.25)
            wait_s = AI_SUMMARY_RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1)) + jitter
            time.sleep(wait_s)

    if last_exc is not None:
        raise last_exc
    return fallback_text


def generate_ai_analyzer_markdown(analysis_url: str, link_type: str = "log") -> str:
    """Generate markdown report for AI Analyzer URL input."""
    normalized = (analysis_url or "").strip()
    if not normalized:
        raise ValueError("Missing analysis URL.")

    user_content = (
        f"Analyze this {link_type} URL and produce a markdown report:\n\n"
        f"{normalized}\n\n"
        "Report should summarize findings, likely root causes, and recommended next checks."
    )
    fallback_text = "AI Analyzer report could not be generated from URL."
    return _call_openclaw_markdown(user_content, AI_ANALYZER_SYSTEM_PROMPT, fallback_text)


def generate_ai_summary_markdown(folder_path: str, analysis_url: str | None = None) -> str:
    """
    Send OpenClaw a single chat-completions request for markdown report generation.
    When analysis_url is provided, only the URL and instructions are sent; OpenClaw
    fetches and analyzes the log. When not provided (e.g. manual run), local findings
    are gathered and sent in the request.
    Returns markdown string for the report.
    """
    allowed_base = os.path.abspath(folder_path)
    if not os.path.isdir(allowed_base):
        raise ValueError(f"AI summary target directory not found: {allowed_base}")

    if analysis_url:
        user_content = (
            f"Analyze the log, use rd1-pxe-auth skill for access. {analysis_url}\n\n"
            "Write a final markdown report for datacenter GPU/server reliability review."
        )
        fallback_text = "Report could not be generated from URL."
    else:
        rel_files = _list_files_in_folder(allowed_base, recursive=True)
        findings_lines = [
            f"Target folder: {allowed_base}",
            f"Files discovered: {len(rel_files)}",
        ]
        if rel_files:
            findings_lines.append("")
            findings_lines.append("Discovered files (relative paths):")
            findings_lines.extend(f"- {rel}" for rel in rel_files)

        gpu_model = _read_gpu_model_from_sys_info(allowed_base)
        if gpu_model:
            findings_lines.append("")
            findings_lines.append(f"GPU model (from sys_info.txt first line): {gpu_model}")

        test_status_str = _parse_test_status_most_recent(allowed_base)
        if test_status_str:
            findings_lines.append("")
            findings_lines.append(f"Test status (most recent run): {test_status_str}")

        findings_lines.append("")
        findings_lines.append("Important log findings by file:")
        collected_chars = 0
        for rel in rel_files:
            result = str(_tool_read_file(allowed_base, rel))
            if result.startswith("No critical errors found in "):
                continue
            section = f"\n### {rel}\n{result}\n"
            if collected_chars + len(section) > AI_SUMMARY_MAX_CONTEXT_CHARS:
                findings_lines.append("\n... [findings truncated for context budget]")
                break
            findings_lines.append(section)
            collected_chars += len(section)

        findings_text = "\n".join(findings_lines).strip() or "No findings extracted."
        user_content = (
            "Analyze the provided folder findings and write a final markdown report "
            "for datacenter GPU/server reliability review.\n\n"
            f"{findings_text}"
        )
        fallback_text = "# AI Summary\n\n---\n\n" + findings_text

    return _call_openclaw_markdown(
        user_content=user_content,
        system_prompt=AI_SUMMARY_STAGE2_SYSTEM_PROMPT,
        fallback_text=fallback_text,
    )
