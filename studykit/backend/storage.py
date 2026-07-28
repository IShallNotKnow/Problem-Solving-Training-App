import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from exceptions import StorageError
from supabase import AsyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage — always uses service client
# ---------------------------------------------------------------------------


class StorageManager:
    def __init__(self, supabase: AsyncClient):
        self.db = supabase
        self.SAFE_FILENAME = re.compile(r"^[\w\-]+\.(png|jpg|jpeg|webp)$")

    async def list_images(self, session_id: UUID) -> list[dict]:
        logger.debug(f"[storage] listing images for session {session_id}")
        response = await (
            self.db.table("generation_images")
            .select("*, generation_inputs!inner(session_id)")
            .eq("generation_inputs.session_id", str(session_id))
            .execute()
        )
        logger.info(f"[storage] found {len(response.data)} images for session {session_id}")
        return response.data

    async def store_pdf(self, session_id: UUID, pdf_bytes: bytes, filename: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = f"{session_id}/{Path(filename).stem}_{timestamp}.pdf"
        logger.info(f"[storage] storing PDF at {path} ({len(pdf_bytes)} bytes)")
        try:
            await self.db.storage.from_("generation-pdfs").upload(
                path=path,
                file=pdf_bytes,
                file_options={"content-type": "application/pdf"},
            )
            logger.info(f"[storage] PDF stored successfully at {path}")
            return path
        except Exception as e:
            raise StorageError("upload", path, cause=e) from e

    async def download_image(self, session_id: UUID, storage_path: str) -> bytes | None:
        try:
            filename = Path(storage_path).name
            if not filename or not self.SAFE_FILENAME.match(filename):
                logger.warning(f"[storage] rejected unsafe image path: {storage_path}")
                return None
            expected_path = f"{session_id}/{filename}"
            if storage_path != expected_path:
                logger.warning(f"[storage] path mismatch: {storage_path} != {expected_path}")
                return None
            session = (
                await self.db.table("sessions")
                .select("session_id")
                .eq("session_id", str(session_id))
                .maybe_single()
                .execute()
            )
            if not session.data:
                logger.warning(f"[storage] session {session_id} not found when downloading image")
                return None
            data = await self.db.storage.from_("generation-images").download(storage_path)
            logger.debug(f"[storage] downloaded image {storage_path} ({len(data)} bytes)")
            return data
        except Exception as e:
            logger.error(f"[storage] failed to download image {storage_path}: {e}")
            return None

    async def store_images(
        self, session_id: UUID, images: list[dict], image_descriptions: dict[str, str]
    ) -> list[dict]:
        ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/jpg"}
        logger.info(f"[storage] storing {len(images)} images for session {session_id}")

        async with httpx.AsyncClient() as http_client:

            async def fetch_and_store(img: dict) -> dict | None:
                path = None
                try:
                    response = await http_client.get(img["url"])
                    if response.status_code != 200:
                        logger.warning(
                            f"[storage] failed to fetch image {img.get('filename')}: HTTP {response.status_code}"
                        )
                        return None
                    content_type = img.get("content_type", "image/png")
                    if content_type not in ALLOWED_CONTENT_TYPES:
                        logger.warning(
                            f"[storage] unsupported content type {content_type} for {img.get('filename')}, defaulting to image/png"
                        )
                        content_type = "image/png"
                    path = f"{session_id}/{uuid4().hex}_{img['filename']}"
                    await self.db.storage.from_("generation-images").upload(
                        path=path,
                        file=response.content,
                        file_options={"content-type": content_type},
                    )
                    logger.debug(f"[storage] stored image {img.get('filename')} at {path}")
                    return {
                        **{k: v for k, v in img.items() if k not in ("url", "content_type")},
                        "storage_path": path,
                        "content_type": content_type,
                        "description": image_descriptions.get(img["filename"]),
                    }
                except StorageError:
                    raise
                except Exception as e:
                    logger.error(f"[storage] error storing image {img.get('filename')}: {e}")
                    if path:
                        await self.db.storage.from_("generation-images").remove([path])
                    raise

            results = await asyncio.gather(
                *(fetch_and_store(img) for img in images), return_exceptions=True
            )
            failed = [r for r in results if isinstance(r, Exception)]
            succeeded = [r for r in results if isinstance(r, dict)]
            if failed:
                logger.error(
                    f"[storage] {len(failed)}/{len(images)} images failed to store for session {session_id}: {failed}"
                )
            logger.info(
                f"[storage] stored {len(succeeded)}/{len(images)} images successfully for session {session_id}"
            )
            return succeeded
