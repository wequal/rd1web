import html
import logging
import threading
import uuid

import markdown
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..ai_summary import generate_ai_analyzer_markdown
from ..form import AiAnalyzerForm

logger = logging.getLogger(__name__)

AI_ANALYZER_TASK_TTL_SEC = 1800


def _render_markdown_fragment(text: str) -> str:
    try:
        return markdown.markdown(text or "", extensions=["extra"])
    except Exception as exc:
        logger.warning("AI Analyzer markdown render failed: %s", exc)
        return f"<pre>{html.escape(text or '')}</pre>"


def _run_ai_analyzer_task(task_id: str, source_url: str, source_type: str, user_id: int):
    cache_key = f"ai_analyzer_task_{task_id}"
    try:
        cache.set(
            cache_key,
            {
                "status": "processing",
                "progress": 20,
                "message": "Analyzing submitted URL with OpenClaw...",
                "markdown": "",
                "report_html": "",
                "error": None,
                "owner_id": user_id,
            },
            AI_ANALYZER_TASK_TTL_SEC,
        )

        markdown_report = generate_ai_analyzer_markdown(source_url, link_type=source_type)
        report_html = _render_markdown_fragment(markdown_report)

        cache.set(
            cache_key,
            {
                "status": "completed",
                "progress": 100,
                "message": "AI analysis completed.",
                "markdown": markdown_report,
                "report_html": report_html,
                "error": None,
                "owner_id": user_id,
            },
            AI_ANALYZER_TASK_TTL_SEC,
        )
    except Exception as exc:
        err = str(exc)
        logger.exception("AI Analyzer task failed for %s: %s", source_url, err)
        cache.set(
            cache_key,
            {
                "status": "failed",
                "progress": 0,
                "message": f"AI analysis failed: {err}",
                "markdown": "",
                "report_html": "",
                "error": err,
                "owner_id": user_id,
            },
            AI_ANALYZER_TASK_TTL_SEC,
        )


@login_required
def ai_analyzer(request):
    return render(request, "features/ai_analyzer.html", {"form": AiAnalyzerForm()})


@login_required
@require_POST
def ai_analyzer_run(request):
    form = AiAnalyzerForm(request.POST)
    if not form.is_valid():
        errors = []
        if form.non_field_errors():
            errors.extend([str(e) for e in form.non_field_errors()])
        for _field, field_errors in form.errors.items():
            if _field == "__all__":
                continue
            errors.extend([str(e) for e in field_errors])
        return JsonResponse(
            {"success": False, "error": " ".join(errors) or "Invalid input."},
            status=400,
        )

    source_url = form.cleaned_data["selected_link"]
    source_type = form.cleaned_data["selected_link_type"]
    task_id = str(uuid.uuid4())
    cache.set(
        f"ai_analyzer_task_{task_id}",
        {
            "status": "initializing",
            "progress": 0,
            "message": "Preparing AI analysis...",
            "markdown": "",
            "report_html": "",
            "error": None,
            "owner_id": request.user.id,
        },
        AI_ANALYZER_TASK_TTL_SEC,
    )

    thread = threading.Thread(
        target=_run_ai_analyzer_task,
        args=(task_id, source_url, source_type, request.user.id),
        daemon=True,
    )
    thread.start()

    return JsonResponse({"success": True, "task_id": task_id, "message": "AI analysis started."})


@login_required
def ai_analyzer_status(request, task_id):
    task_data = cache.get(f"ai_analyzer_task_{task_id}")
    if not task_data:
        return JsonResponse({"success": False, "error": "Task not found"}, status=404)

    if task_data.get("owner_id") != request.user.id:
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)

    return JsonResponse(
        {
            "success": True,
            "status": task_data.get("status"),
            "progress": task_data.get("progress", 0),
            "message": task_data.get("message", ""),
            "markdown": task_data.get("markdown", ""),
            "report_html": task_data.get("report_html", ""),
            "error": task_data.get("error"),
        }
    )
