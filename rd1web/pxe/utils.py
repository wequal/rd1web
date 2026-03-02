import os
import logging
import markdown
from .views.system_details import get_file_content, parse_sysconfig

logger = logging.getLogger(__name__)
BASE_DIR = '/srv/log'


def render_markdown_as_html(file_content, filename):
    """Convert markdown file content to a full HTML document for viewing in the browser."""
    try:
        html_body = markdown.markdown(
            file_content,
            extensions=['extra'],
        )
    except Exception as e:
        logger.warning("Markdown conversion failed for %s: %s", filename, e)
        html_body = '<pre>' + _escape_html(file_content) + '</pre>'
    html_doc = f"""<!DOCTYPE html>
<html>
<head>
    <title>{_escape_html(filename)}</title>
    <meta charset="utf-8">
    <style>
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            min-height: 100%;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            padding: 20px;
            background-color: #f8f9fa;
            line-height: 1.5;
        }}
        .md-container {{
            width: 100%;
            max-width: 100%;
            background: white;
            padding: 24px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            box-sizing: border-box;
        }}
        h1, h2, h3, h4, h5, h6 {{ margin-top: 1.2em; margin-bottom: 0.5em; font-weight: 600; }}
        h1 {{ font-size: 1.6em; border-bottom: 1px solid #dee2e6; padding-bottom: 0.3em; }}
        h2 {{ font-size: 1.35em; border-bottom: 1px solid #dee2e6; padding-bottom: 0.25em; }}
        h3 {{ font-size: 1.15em; }}
        pre {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; padding: 12px; overflow-x: auto; font-size: 13px; }}
        code {{ background: #f8f9fa; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
        pre code {{ background: none; padding: 0; }}
        ul, ol {{ margin: 0.5em 0; padding-left: 1.5em; }}
        blockquote {{ border-left: 4px solid #dee2e6; margin: 0.5em 0; padding-left: 1em; color: #6c757d; }}
        table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; font-size: 14px; }}
        th, td {{ border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }}
        th {{ background-color: #f8f9fa; font-weight: 600; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
    </style>
</head>
<body>
    <div class="md-container">{html_body}</div>
</body>
</html>"""
    return html_doc


def _escape_html(text):
    """Escape HTML special characters for safe use in title/fallback content."""
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def get_system_sysconfig(folder_name: str):
    """Return parsed sysconfig for *folder_name* or *None* if missing."""
    log_dir = os.path.join(BASE_DIR, folder_name)
    if not os.path.exists(log_dir):
        logger.error("Log directory not found: %s", log_dir)
        return None

    sysconfig_path = os.path.join(log_dir, 'sysconfig')
    sysconfig_content = get_file_content(sysconfig_path)
    if not sysconfig_content:
        logger.error("Failed to read sysconfig file: %s", sysconfig_path)
        return None

    config = parse_sysconfig(sysconfig_content)
    logger.info("Loaded sysconfig for %s: BMC IP = %s", folder_name, config.get('bmc_ip', 'N/A'))
    return config 