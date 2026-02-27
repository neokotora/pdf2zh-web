"""
Translation service: wraps high_level.py and bridges events to TaskService.

Handles:
- Building SettingsModel from user config
- Running translation with progress updates
- Concurrency control via semaphore
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.high_level import do_translate_async_stream
from pdf2zh_next.services.settings_service import get_settings_service
from pdf2zh_next.services.task_service import get_task_service

logger = logging.getLogger(__name__)

MAX_CONCURRENT_TRANSLATIONS = int(
    os.environ.get("MAX_CONCURRENT_TRANSLATIONS", "1")
)
translation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRANSLATIONS)


def build_settings_model_from_user_config(
    user_settings: dict, output_dir: Path, pages: str | None = None
) -> SettingsModel:
    """Build SettingsModel from user's saved settings."""
    from pdf2zh_next.config.translate_engine_model import (
        AnythingLLMSettings,
        AzureOpenAISettings,
        BingSettings,
        ClaudeCodeSettings,
        DeepLSettings,
        DeepSeekSettings,
        GeminiSettings,
        GoogleSettings,
        OllamaSettings,
        OpenAISettings,
        SiliconFlowFreeSettings,
        SiliconFlowSettings,
        TencentSettings,
        ZhipuSettings,
    )

    service = user_settings.get("service", "SiliconFlowFree")

    engine_settings = None
    if service == "OpenAI":
        engine_settings = OpenAISettings(
            openai_model=user_settings.get("openai_model", "gpt-4o-mini"),
            openai_api_key=user_settings.get("openai_api_key", ""),
            openai_base_url=user_settings.get(
                "openai_base_url", "https://api.openai.com/v1"
            ),
        )
    elif service == "AzureOpenAI":
        engine_settings = AzureOpenAISettings(
            azure_openai_api_key=user_settings.get("azure_openai_api_key", ""),
            azure_openai_base_url=user_settings.get("azure_openai_base_url", ""),
            azure_openai_model=user_settings.get("azure_openai_model", ""),
            azure_openai_api_version=user_settings.get(
                "azure_openai_api_version", "2024-02-15-preview"
            ),
        )
    elif service in ("Gemini", "GoogleGemini"):
        engine_settings = GeminiSettings(
            gemini_model=user_settings.get("gemini_model", "gemini-1.5-flash"),
            gemini_api_key=user_settings.get("gemini_api_key", ""),
        )
    elif service == "DeepL":
        engine_settings = DeepLSettings(
            deepl_auth_key=user_settings.get("deepl_api_key", ""),
        )
    elif service == "Ollama":
        engine_settings = OllamaSettings(
            ollama_model=user_settings.get("ollama_model", "gemma2"),
            ollama_host=user_settings.get(
                "ollama_host", "http://127.0.0.1:11434"
            ),
        )
    elif service == "SiliconFlow":
        engine_settings = SiliconFlowSettings(
            siliconflow_model=user_settings.get(
                "siliconflow_model", "Qwen/Qwen2.5-7B-Instruct"
            ),
            siliconflow_api_key=user_settings.get("siliconflow_api_key", ""),
        )
    elif service == "DeepSeek":
        engine_settings = DeepSeekSettings(
            deepseek_model=user_settings.get("deepseek_model", "deepseek-chat"),
            deepseek_api_key=user_settings.get("deepseek_api_key", ""),
        )
    elif service == "Zhipu":
        engine_settings = ZhipuSettings(
            zhipu_model=user_settings.get("zhipu_model", "glm-4-flash"),
            zhipu_api_key=user_settings.get("zhipu_api_key", ""),
        )
    elif service == "Claude":
        engine_settings = ClaudeCodeSettings(
            claudecode_model=user_settings.get(
                "claude_model", "claude-sonnet-4-20250514"
            ),
            claudecode_api_key=user_settings.get("claude_api_key", ""),
        )
    elif service == "Bing":
        engine_settings = BingSettings()
    elif service == "Google":
        engine_settings = GoogleSettings()
    elif service == "Tencent":
        engine_settings = TencentSettings(
            tencentcloud_secret_id=user_settings.get("tencent_secret_id", ""),
            tencentcloud_secret_key=user_settings.get("tencent_secret_key", ""),
        )
    else:
        engine_settings = SiliconFlowFreeSettings()

    settings = SettingsModel(
        translate_engine_settings=engine_settings,
        report_interval=0.5,
    )

    # Translation settings
    settings.translation.lang_in = user_settings.get("lang_from", "en")
    settings.translation.lang_out = user_settings.get("lang_to", "zh")
    settings.translation.output = str(output_dir)
    settings.translation.ignore_cache = user_settings.get("ignore_cache", False)
    settings.translation.qps = user_settings.get(
        "custom_qps", user_settings.get("qps", 4)
    )

    min_text_length = user_settings.get("min_text_length", 5)
    if min_text_length:
        settings.translation.min_text_length = min_text_length

    rpc_doclayout = user_settings.get("rpc_doclayout", "")
    if rpc_doclayout:
        settings.translation.rpc_doclayout = rpc_doclayout

    custom_prompt = user_settings.get("custom_system_prompt", "")
    if custom_prompt:
        settings.translation.custom_system_prompt = custom_prompt

    primary_font = user_settings.get("primary_font", "")
    if primary_font and primary_font != "auto":
        settings.translation.primary_font_family = primary_font

    custom_workers = user_settings.get("custom_workers", 0)
    if custom_workers and custom_workers > 0:
        settings.translation.pool_max_workers = custom_workers

    # Term extraction
    settings.translation.no_auto_extract_glossary = not user_settings.get(
        "enable_term_extraction", False
    )
    settings.translation.save_auto_extracted_glossary = user_settings.get(
        "save_glossary", False
    )
    term_qps = user_settings.get("term_qps", 0)
    if term_qps and term_qps > 0:
        settings.translation.term_qps = term_qps
    term_workers = user_settings.get("term_workers", 0)
    if term_workers and term_workers > 0:
        settings.translation.term_pool_max_workers = term_workers

    # PDF settings
    if pages:
        settings.pdf.pages = pages
    settings.pdf.no_dual = user_settings.get("no_dual", False)
    settings.pdf.no_mono = user_settings.get("no_mono", False)
    settings.pdf.dual_translate_first = user_settings.get(
        "dual_translate_first", False
    )
    settings.pdf.skip_clean = user_settings.get("skip_clean", False)
    settings.pdf.enhance_compatibility = user_settings.get(
        "enhance_compatibility", False
    )
    settings.pdf.ocr_workaround = user_settings.get("ocr_workaround", False)
    settings.pdf.translate_table_text = user_settings.get(
        "translate_tables", user_settings.get("translate_table_text", True)
    )
    settings.pdf.split_short_lines = user_settings.get("split_short_lines", False)
    settings.pdf.short_line_split_factor = user_settings.get("split_factor", 0.8)
    settings.pdf.disable_rich_text_translate = user_settings.get(
        "disable_rich_text", False
    )
    settings.pdf.use_alternating_pages_dual = user_settings.get(
        "use_alternating_pages", False
    )
    settings.pdf.skip_scanned_detection = user_settings.get(
        "skip_scanned_detection", False
    )
    settings.pdf.only_include_translated_page = user_settings.get(
        "only_translated_pages", False
    )
    settings.pdf.auto_enable_ocr_workaround = user_settings.get("auto_ocr", False)

    max_pages = user_settings.get("max_pages_per_part", 0)
    if max_pages and max_pages > 0:
        settings.pdf.max_pages_per_part = max_pages

    formula_font = user_settings.get("formula_font_pattern", "")
    if formula_font:
        settings.pdf.formular_font_pattern = formula_font
    formula_char = user_settings.get("formula_char_pattern", "")
    if formula_char:
        settings.pdf.formular_char_pattern = formula_char

    # BabelDOC settings
    settings.pdf.no_merge_alternating_line_numbers = not user_settings.get(
        "merge_line_numbers", False
    )
    settings.pdf.no_remove_non_formula_lines = not user_settings.get(
        "remove_formula_lines", False
    )
    settings.pdf.non_formula_line_iou_threshold = user_settings.get(
        "iou_threshold", 0.9
    )
    settings.pdf.figure_table_protection_threshold = user_settings.get(
        "protection_threshold", 0.9
    )
    settings.pdf.skip_formula_offset_calculation = user_settings.get(
        "skip_formula_offset", False
    )

    watermark_mode = user_settings.get("watermark_mode", "watermarked")
    settings.pdf.watermark_output_mode = watermark_mode

    return settings


async def run_translation(
    task_id: str,
    file_path: Path,
    output_dir: Path,
    translation_settings: dict,
    username: str,
):
    """Run a translation task with semaphore-based concurrency control."""
    task_service = get_task_service()
    original_filename = file_path.stem
    mono_path = None
    dual_path = None

    try:
        task_service.update_progress(
            task_id, 0, "Waiting in queue...", "queued"
        )

        async with translation_semaphore:
            task_service.update_progress(
                task_id, 0, "Loading user settings...", "processing"
            )

            # Load user settings via encrypted settings service
            settings_svc = get_settings_service()
            user_settings = await settings_svc.get_settings(username)

            pages = translation_settings.get("pages") if translation_settings else None

            logger.info(
                f"Starting translation task {task_id} for user {username}"
            )

            settings = build_settings_model_from_user_config(
                user_settings, output_dir, pages
            )

            try:
                settings.validate_settings()
            except ValueError as e:
                raise ValueError(f"Invalid translation settings: {e}")

            task_service.update_progress(
                task_id, 0, "Starting translation...", "processing"
            )

            async for event in do_translate_async_stream(settings, file_path):
                if event["type"] in (
                    "progress_start",
                    "progress_update",
                    "progress_end",
                ):
                    stage = event.get("stage", "Processing")
                    progress = event.get("overall_progress", 0)
                    part_index = event.get("part_index", 1)
                    total_parts = event.get("total_parts", 1)
                    stage_current = event.get("stage_current", 0)
                    stage_total = event.get("stage_total", 1)

                    message = (
                        f"{stage} ({part_index}/{total_parts},"
                        f" {stage_current}/{stage_total})"
                    )
                    task_service.update_progress(
                        task_id, int(progress), message, "processing"
                    )

                elif event["type"] == "finish":
                    result = event["translate_result"]
                    result_mono_path = result.mono_pdf_path
                    result_dual_path = result.dual_pdf_path

                    if result_mono_path and result_mono_path.exists():
                        mono_path = output_dir / f"{original_filename}_mono.pdf"
                        result_mono_path.rename(mono_path)

                    if result_dual_path and result_dual_path.exists():
                        dual_path = output_dir / f"{original_filename}_dual.pdf"
                        result_dual_path.rename(dual_path)

                    break

                elif event["type"] == "error":
                    error_msg = event.get("error", "Unknown error")
                    raise RuntimeError(f"Translation error: {error_msg}")

            task_service.complete_task(
                task_id,
                mono_path=str(mono_path) if mono_path else None,
                dual_path=str(dual_path) if dual_path else None,
            )
            logger.info(f"Translation task {task_id} completed")

    except Exception as e:
        logger.error(f"Translation task {task_id} failed: {e}", exc_info=True)
        task_service.fail_task(task_id, str(e))
