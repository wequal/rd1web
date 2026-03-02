#!/usr/bin/env python3
"""
Manual test for AI Summary API using the same tool-calling agent loop as the
user's script (and the Django backend). Uses list_files_in_folder and
read_file_content tools so the model can explore the folder and return content.

Usage:
  python3 rd1web/pxe/test_ai_summary_manual.py
  python3 rd1web/pxe/test_ai_summary_manual.py /path/to/log/folder

Default folder: /srv/rma-b31/gb/1654025041108-1654025040938_RD260116075
"""
import json
import os
import re
import sys
from collections import deque

VLLM_BASE_URL = "http://172.31.57.161:8000/v1"
VLLM_API_KEY = "token"
MODEL_NAME = "Qwen3.5-35B"
MAX_FILE_SIZE_MB = 200
MAX_ERROR_LINES = 200
MAX_FILES_TO_LIST = 400
REQUEST_TIMEOUT_SEC = 120.0
MAX_TOOL_ITERATIONS = 18
ERROR_REGEX = re.compile(r"error|fail|fatal|exception|traceback", re.IGNORECASE)

DEFAULT_FOLDER = "/srv/rma-b31/gb/1654025041108-1654025040938_RD260116075"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files_in_folder",
            "description": "List all files in the given folder path (non-recursive).",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {"type": "string", "description": "Absolute or relative path to the folder"}
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
                    "file_path": {"type": "string", "description": "Absolute or relative path to the file"}
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        },
    },
]


def list_files_in_folder(folder_path: str):
    full = os.path.abspath(folder_path)
    if not os.path.isdir(full):
        return f"Error: {folder_path} is not a valid directory."
    names = []
    for entry in os.listdir(full):
        p = os.path.join(full, entry)
        if os.path.isfile(p):
            names.append(entry)
    names.sort()
    if not names:
        return "No files found in folder."
    if len(names) > MAX_FILES_TO_LIST:
        return f"Found {len(names)} files. First {MAX_FILES_TO_LIST}:\n" + "\n".join(names[:MAX_FILES_TO_LIST])
    return names


def read_file_content(file_path: str) -> str:
    full = os.path.abspath(file_path)
    if not os.path.isfile(full):
        return f"Error: {file_path} is not a valid file."
    size_mb = os.path.getsize(full) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return f"Skipped {file_path}: File too large ({size_mb:.1f} MB)."
    lines = deque(maxlen=MAX_ERROR_LINES)
    try:
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if ERROR_REGEX.search(line):
                    lines.append(line.rstrip())
    except Exception as e:
        return f"Error reading file {file_path}: {e}"
    if not lines:
        return f"No critical errors found in {file_path}."
    return "\n".join(lines)


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FOLDER
    folder = os.path.abspath(os.path.normpath(folder))

    if not os.path.isdir(folder):
        print(f"Error: not a directory: {folder}", file=sys.stderr)
        sys.exit(1)

    print(f"Folder: {folder}")
    print(f"API:   {VLLM_BASE_URL}  model={MODEL_NAME}  timeout={REQUEST_TIMEOUT_SEC}s")
    print("Using tool-calling agent loop (list_files_in_folder, read_file_content)")
    print()

    from openai import OpenAI

    client = OpenAI(base_url=VLLM_BASE_URL, api_key=VLLM_API_KEY, max_retries=0)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior datacenter GPU and server reliability engineer.\n"
                "Focus on clarity, precision, and engineering reasoning."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Scan folder {folder}\n"
                "1. Summarize the logs.\n"
                "2. Hypothesize the root causes.\n"
                "3. Do not write action plan.\n"
                "4. For the MI* ADDC Analyzer log: count failed OAM modules ONLY by the number of "
                "individual modules that have a named fatal error entry (oam: X). Never say \"all 8\" or "
                "\"0-7\" unless you see 8 separate named entries. If fewer than 8 are explicitly named, "
                "state the exact confirmed number. Also show how many times the issue occurred and error category."
            ),
        },
    ]

    def parse_args(raw: str):
        if not raw:
            return {}
        try:
            p = json.loads(raw)
            return p if isinstance(p, dict) else {}
        except json.JSONDecodeError:
            return {}

    for turn in range(1, MAX_TOOL_ITERATIONS + 1):
        print(f"Turn {turn}...", flush=True)
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=2048,
                temperature=0.0,
                top_p=1.0,
                seed=2026,
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except Exception as e:
            print(f"API call failed: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)

        msg = response.choices[0].message if response.choices else None
        if not msg:
            break

        messages.append(msg.model_dump(exclude_none=True))
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            content = getattr(msg, "content", None) or ""
            print("OK. Final response:")
            print("---")
            print(content.strip() or "(empty)")
            print("---")
            return

        print(f"  -> {len(tool_calls)} tool call(s)")
        for tc in tool_calls:
            name = getattr(tc.function, "name", "") if getattr(tc, "function", None) else ""
            args_str = getattr(tc.function, "arguments", None) or "{}"
            args = parse_args(args_str)
            tid = getattr(tc, "id", "") or ""

            if name == "list_files_in_folder":
                result = list_files_in_folder(args.get("folder_path", ""))
            elif name == "read_file_content":
                result = read_file_content(args.get("file_path", ""))
            else:
                result = "Error: Requested tool not found."

            if isinstance(result, list):
                result = "\n".join(result) if result else "No files found in folder."
            messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "name": name,
                "content": str(result),
            })

    print("Max tool iterations reached without final response.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
