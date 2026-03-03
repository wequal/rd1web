#!/usr/bin/env python3
"""
Manual run script for AI Summary: uses the same two-stage flow as the Django app
(Stage 1 discovery + Stage 2 report via write_report tool) and writes the
report to the script's directory as AI_Report_<timestamp>.md.

Usage (from project root /home/devin/rd1web-dev):
  source venv/bin/activate
  python3 rd1web/pxe/run_ai_summary_manual.py
  python3 rd1web/pxe/run_ai_summary_manual.py /path/to/log/folder

Default folder: /srv/rma-b31/gb/1654025041108-1654025040938_RD260116075
"""
import os
import sys
from datetime import datetime

# Ensure project root is on path so rd1web.pxe can be imported
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

DEFAULT_FOLDER = "/srv/rma-b31/692452100644_XD260129045"


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FOLDER
    folder = os.path.abspath(os.path.normpath(folder))

    if not os.path.isdir(folder):
        print(f"Error: not a directory: {folder}", file=sys.stderr)
        sys.exit(1)

    from rd1web.pxe.ai_summary import (
        generate_ai_summary_markdown,
        AI_SUMMARY_VLLM_BASE_URL,
        AI_SUMMARY_MODEL_NAME,
        AI_SUMMARY_REQUEST_TIMEOUT_SEC,
    )

    print(f"Folder: {folder}")
    print(f"API:   {AI_SUMMARY_VLLM_BASE_URL}  model={AI_SUMMARY_MODEL_NAME}  timeout={AI_SUMMARY_REQUEST_TIMEOUT_SEC}s")
    print("Running two-stage AI summary (Stage 1 discovery, Stage 2 write_report)...")
    print()

    try:
        markdown_content = generate_ai_summary_markdown(folder)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"AI_Report_{timestamp}.md"
    report_path = os.path.join(_script_dir, report_filename)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"Report written: {report_path}")
    print(f"Length: {len(markdown_content)} chars")
    print()
    print("--- Preview (first 800 chars) ---")
    print(markdown_content[:800].rstrip())
    if len(markdown_content) > 800:
        print("...")
    print("---")


if __name__ == "__main__":
    main()
