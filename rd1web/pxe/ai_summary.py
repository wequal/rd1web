"""
AI summary generation for RMA/GB log folders: OpenAI-compatible API calls
(two-stage: discovery with tools, then report). Used by rma_logs views.
"""
import json
import os
import random
import re
import time
from collections import deque

# Config (can be overridden from local_config later)
AI_SUMMARY_VLLM_BASE_URL = "http://172.31.57.161:8000/v1"
AI_SUMMARY_VLLM_API_KEY = "token"
AI_SUMMARY_MODEL_NAME = "Qwen3.5-35B"
AI_SUMMARY_MAX_FILE_SIZE_MB = 200
AI_SUMMARY_MAX_ERROR_LINES = 200
AI_SUMMARY_MAX_FILES_TO_LIST = 400
AI_SUMMARY_REQUEST_TIMEOUT_SEC = 120.0
# Tuned for --max-model-len 98304 (~4 chars/token: reserve headroom for prompts + response)
AI_SUMMARY_MAX_CONTEXT_CHARS = 360000   # ~90k tokens context budget
AI_SUMMARY_MAX_READ_CHARS = 18000       # max chars returned per file (context budget / 20)
AI_SUMMARY_MAX_TOOL_ITERATIONS = 18
AI_SUMMARY_MAX_RETRIES = 3
AI_SUMMARY_RETRY_BACKOFF_BASE_SEC = 1.0
AI_SUMMARY_ERROR_REGEX = re.compile(r"error|fail|fatal|exception|traceback", re.IGNORECASE)

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

3. GB* GPUs:
- Skip:
    SyslogErrorCheck
    KernLogErrorCheck
    DmesgLogErrorCheck
    SyslogAERCheck
    KernLogAERCheck
    DmesgLogAERCheck
- Do not mention them.

FORMATTING RULES

- Use clean, professional markdown.
- Use horizontal rules (---) between major sections.
- Use bullet or numbered lists for clarity.
- Keep lines roughly 60–75 characters.
- Make the report easy to scan.
"""


def generate_ai_summary_markdown(folder_path: str) -> str:
    """
    Run two-stage AI summary: Stage 1 discovery (tool loop), Stage 2 report.
    Returns markdown string for the report.
    """
    from openai import OpenAI

    allowed_base = os.path.abspath(folder_path)
    client = OpenAI(
        base_url=AI_SUMMARY_VLLM_BASE_URL,
        api_key=AI_SUMMARY_VLLM_API_KEY,
        max_retries=0,
    )

    def parse_tool_args(raw: str):
        if not raw:
            return {}
        try:
            p = json.loads(raw)
            return p if isinstance(p, dict) else {}
        except json.JSONDecodeError:
            return {}

    # ─── Stage 1: Discovery (tool loop, raw findings only) ───
    stage1_user_content = f"Scan folder {folder_path} and output your raw findings and notes. Do not write the final report yet."
    gpu_model = _read_gpu_model_from_sys_info(allowed_base)
    if gpu_model:
        stage1_user_content += f"\n\nGPU model (from sys_info.txt first line): {gpu_model}"
    test_status_str = _parse_test_status_most_recent(allowed_base)
    if test_status_str:
        stage1_user_content += f"\n\nTest status (most recent run): {test_status_str}"

    stage1_messages = [
        {
            "role": "system",
            "content": (
                "You are a senior datacenter GPU and server reliability engineer. "
                "Explore the given folder and output raw findings only: list files you read, key errors, "
                "test results, MI3XX ADDC/OAM notes if applicable, "
                "and any other relevant facts. Output structured notes; do not write the final report."
            ),
        },
        {
            "role": "user",
            "content": stage1_user_content,
        },
    ]

    def stage1_call():
        return client.chat.completions.create(
            model=AI_SUMMARY_MODEL_NAME,
            messages=stage1_messages,
            tools=AI_SUMMARY_TOOLS,
            tool_choice="auto",
            max_tokens=2048,
            temperature=0.0,
            top_p=1.0,
            seed=2026,
            timeout=AI_SUMMARY_REQUEST_TIMEOUT_SEC,
        )

    stage1_findings = "No findings extracted."
    for turn in range(1, AI_SUMMARY_MAX_TOOL_ITERATIONS + 1):
        last_exc = None
        for attempt in range(1, AI_SUMMARY_MAX_RETRIES + 1):
            try:
                response = stage1_call()
                last_exc = None
                break
            except Exception as api_exc:
                last_exc = api_exc
                if attempt == AI_SUMMARY_MAX_RETRIES:
                    raise
                jitter = random.uniform(0.0, 0.25)
                wait_s = AI_SUMMARY_RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1)) + jitter
                time.sleep(wait_s)
        if last_exc is not None:
            raise last_exc

        choice = response.choices[0] if response.choices else None
        if not choice:
            break
        msg = choice.message
        stage1_messages.append(msg.model_dump(exclude_none=True))

        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            content = getattr(msg, "content", None) or ""
            stage1_findings = (content or "").strip() or "No findings extracted."
            break

        for tc in tool_calls:
            name = getattr(tc, "function", None) and getattr(tc.function, "name", None) or ""
            args_str = getattr(tc.function, "arguments", None) or "{}"
            args = parse_tool_args(args_str)
            tid = getattr(tc, "id", None) or ""
            if name == "list_files_in_folder":
                result = _tool_list_files(
                    allowed_base,
                    args.get("folder_path", ""),
                    recursive=bool(args.get("recursive", False)),
                )
            elif name == "read_file_content":
                result = _tool_read_file(allowed_base, args.get("file_path", ""))
            else:
                result = "Error: Requested tool not found."
            if isinstance(result, list):
                result = "\n".join(result) if result else "No files found in folder."
            content = str(result)
            # Smart trim: keep total Stage 1 context under limit
            trunc_suffix = "\n[truncated for context limit]"
            current_total = sum(len((m.get("content") or "")) for m in stage1_messages)
            if current_total + len(content) > AI_SUMMARY_MAX_CONTEXT_CHARS:
                max_content = max(0, AI_SUMMARY_MAX_CONTEXT_CHARS - current_total - len(trunc_suffix))
                content = content[:max_content] + trunc_suffix
            stage1_messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "name": name,
                "content": content,
            })
    else:
        stage1_findings = "Max iterations reached; partial or no findings."

    # ─── Stage 2: Report via write_report tool (avoids vLLM returning empty message.content) ───
    stage2_messages = [
        {"role": "system", "content": AI_SUMMARY_STAGE2_SYSTEM_PROMPT.strip()},
        {
            "role": "user",
            "content": f"Using the following findings, write the final markdown report. You must call the write_report tool once with the complete report in the markdown_report argument.\n\n---\n\n{stage1_findings}",
        },
    ]

    last_exc = None
    for attempt in range(1, AI_SUMMARY_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=AI_SUMMARY_MODEL_NAME,
                messages=stage2_messages,
                tools=AI_SUMMARY_STAGE2_TOOL,
                tool_choice={"type": "function", "function": {"name": "write_report"}},
                max_tokens=4096,
                temperature=0.0,
                top_p=1.0,
                seed=2026,
                timeout=AI_SUMMARY_REQUEST_TIMEOUT_SEC,
            )
            last_exc = None
            break
        except Exception as api_exc:
            last_exc = api_exc
            if attempt == AI_SUMMARY_MAX_RETRIES:
                raise
            jitter = random.uniform(0.0, 0.25)
            wait_s = AI_SUMMARY_RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1)) + jitter
            time.sleep(wait_s)
    if last_exc is not None:
        raise last_exc

    content = ""
    if response.choices:
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            name = getattr(tc, "function", None) and getattr(tc.function, "name", None) or ""
            if name == "write_report":
                args_str = getattr(tc.function, "arguments", None) or "{}"
                args = parse_tool_args(args_str)
                content = args.get("markdown_report") or ""
                break
        if not (content or "").strip():
            content = getattr(msg, "content", None)
            if content is None and hasattr(msg, "model_dump"):
                try:
                    d = msg.model_dump() or {}
                    content = d.get("content") or d.get("reasoning_content")
                except Exception:
                    pass
            if not (content or "").strip() and getattr(msg, "reasoning_content", None):
                content = msg.reasoning_content
    content = (content or "").strip()
    if not content:
        content = "# AI Summary\n\n---\n\n" + stage1_findings
    return content
