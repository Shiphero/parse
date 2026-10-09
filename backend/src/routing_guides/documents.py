"""Prepare original pages without interpreting or approving retailer rules."""
import asyncio
import logging
from pathlib import Path
import re
import subprocess
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert

from routing_guides.db import sessions
from routing_guides.models import Guide, GuidePage
from routing_guides.storage import guide_directory

logger = logging.getLogger(__name__)


class PreparationError(ValueError):
    pass


def document_page_count(path: Path) -> int:
    result = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60)
    if result.returncode:
        raise PreparationError("The PDF could not be opened. Upload an unlocked, readable copy.")
    info = result.stdout.decode("utf-8", errors="replace")
    if re.search(r"^Encrypted:\s+yes", info, re.MULTILINE):
        raise PreparationError("This PDF is encrypted. Upload an unlocked copy to prepare its pages.")
    match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
    if not match or int(match[1]) < 1:
        raise PreparationError("This PDF does not contain readable pages.")
    return int(match[1])


def prepare_page(directory: Path, index: int, need_text: bool, need_image: bool) -> dict:
    original = directory / "original.pdf"
    page_number = str(index + 1)
    prefix = directory / f"page-{index}"
    result = {}
    if need_text:
        try:
            output = subprocess.run(
                ["pdftotext", "-f", page_number, "-l", page_number, "-layout", "-enc", "UTF-8", str(original), "-"],
                capture_output=True, timeout=90, check=True,
            )
            text = output.stdout.decode("utf-8", errors="replace").replace("\x00", "").strip("\n\r\f ")
            result.update(text=text, text_status="extracted" if text else "no_text")
        except (subprocess.SubprocessError, OSError):
            result.update(text=None, text_status="failed")
    if need_image:
        temporary_prefix = directory / f"page-{index}.preparing"
        try:
            subprocess.run(
                ["pdftoppm", "-f", page_number, "-l", page_number, "-scale-to", "1600", "-singlefile", "-png", str(original), str(temporary_prefix)],
                capture_output=True, timeout=90, check=True,
            )
            Path(f"{temporary_prefix}.png").replace(Path(f"{prefix}.png"))
            result["image_status"] = "ready"
        except (subprocess.SubprocessError, OSError):
            Path(f"{temporary_prefix}.png").unlink(missing_ok=True)
            result["image_status"] = "failed"
    return result


async def prepare_document(guide_id: UUID) -> None:
    directory = guide_directory(guide_id)
    async with sessions.begin() as session:
        guide = await session.get(Guide, guide_id)
        if guide is None or guide.status == "ready":
            return
        guide.status, guide.error = "preparing", None
    try:
        count = await asyncio.to_thread(document_page_count, directory / "original.pdf")
        async with sessions.begin() as session:
            await session.execute(update(Guide).where(Guide.id == guide_id).values(page_count=count))
            # Account for every page before processing; retries retain successful work.
            for start in range(0, count, 500):
                await session.execute(insert(GuidePage).values([
                    {"guide_id": guide_id, "page_index": index}
                    for index in range(start, min(start + 500, count))
                ]).on_conflict_do_nothing())
        for index in range(count):
            async with sessions() as session:
                page = await session.get(GuidePage, (guide_id, index))
                need_text = page.text_status in {"pending", "failed"}
                need_image = page.image_status != "ready" or not (directory / f"page-{index}.png").exists()
            if not need_text and not need_image:
                continue
            values = await asyncio.to_thread(prepare_page, directory, index, need_text, need_image)
            async with sessions.begin() as session:
                page = await session.get(GuidePage, (guide_id, index))
                for key, value in values.items():
                    setattr(page, key, value)
                issues = []
                if page.text_status == "no_text":
                    issues.append("No text was extracted. This page may be scanned, image-only or blank; inspect the original.")
                elif page.text_status == "failed":
                    issues.append("Text extraction failed. Retry preparation or inspect the original PDF.")
                if page.image_status == "failed":
                    issues.append("The page preview could not be generated.")
                page.issue = " ".join(issues) or None
                await session.flush()
                processed, attention = (await session.execute(select(
                    func.count().filter(and_(GuidePage.image_status != "pending", GuidePage.text_status != "pending")),
                    func.count().filter(GuidePage.issue.is_not(None)),
                ).where(GuidePage.guide_id == guide_id))).one()
                await session.execute(update(Guide).where(Guide.id == guide_id).values(
                    processed_pages=processed,
                    attention_pages=attention,
                ))
        async with sessions.begin() as session:
            guide = await session.get(Guide, guide_id)
            guide.status = "needs_attention" if guide.attention_pages else "ready"
    except Exception as exc:
        message = str(exc) if isinstance(exc, PreparationError) else "Preparation stopped before all pages were ready. Retry to resume, or upload a readable copy."
        logger.warning("Guide preparation failed: guide=%s error_type=%s", guide_id, type(exc).__name__)
        async with sessions.begin() as session:
            await session.execute(update(Guide).where(Guide.id == guide_id).values(status="failed", error=message))
        raise
