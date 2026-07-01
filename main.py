from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
from llama_cloud import AsyncLlamaCloud
import tempfile
from dotenv import load_dotenv
import os
from pathlib import Path
import asyncio
import aiofiles

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Uploader:
    ...

class AsyncPDFProcessor:
    def __init__(self):
        self.client = AsyncLlamaCloud(
            api_key=os.getenv("LLAMA_CLOUD_API_KEY")
        )


    async def extract(self, file_bytes: bytes):
        uploaded = await self.client.files.create(
            file=("document.pdf", file_bytes, "application/pdf"),
            purpose="parse",
        )

        job = await self.client.parsing.parse(
            file_id=uploaded.id,
            tier="agentic",
            version="latest",
            expand=[
                "markdown",
                "items",
                "images_content_metadata",
            ],
            output_options={
                "images_to_save": ["layout", "embedded"]
            },
        )

        markdown = getattr(job, "markdown", "") or ""

        items = []
        for pages in getattr(getattr(job, "items", None), "pages", []):
            page_number = getattr(pages, "page_number", 0)
            for item in getattr(pages, "items", []):
                item_data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
                item_data["page_number"] = page_number

                bbox = item_data.get("bbox")
                items.append({
                    "type": item_data.get("type"),
                    "level": item_data.get("level"),
                    "value": item_data.get("value"),
                    "md": item_data.get("md"),
                    "page": page_number,
                    "bbox": bbox.model_dump() if hasattr(bbox, "model_dump") else bbox,
                    "grounding": item_data.get("grounding"),
                })


        images = [
            {
                "filename": img.filename,
                "url": img.presigned_url,
                "page": img.index,
                "bbox": img.bbox.model_dump(),
                "content_type": img.content_type,
                "category": img.category,
            }
            for img in job.images_content_metadata.images
        ]

        return markdown, items, images

class ImageFilter:
    def __init__(self):
        ...
    
    async def heuristic_filter(self, images: list) -> list:
        if not images:
            return None
        
        filtered = []
        exclude_types = {"logo", "icon", "banner", "header", "footer"}

        for image in images:
            width = image["bbox"]["w"]
            height = image["bbox"]["h"]
            if image["content_type"] in exclude_types or height < 100 or width < 100:
                continue

            aspect_ratio = width/height
            if aspect_ratio > 10 or aspect_ratio < 0.1:
                return False

            filtered.append(image)
        
        return filtered
    
    async def semantic_filter(self, images: list, markdown: str) -> list:
        ...


class ConceptExtractor:
    ...

class QuestionGenerator:
    def __init__(self):
        self.client = Anthropic()

    async def generate_questions(self, content: str) -> str:
        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a study assistant. Based on the following content, 
                    generate 10 study questions that test understanding of the key concepts and 
                    problem-solving skills through applied problems.

    Content:
    {content}

    Format each question clearly and numbered."""
                }
            ]
        )
        return message.content[0].text

class QuestionValidator:
    ...


async def main():
    pdf_bytes = Path("test_files/002-shortest-paths-1.pdf").read_bytes()

    processor = AsyncPDFProcessor()
    markdown, items, images = await processor.extract(pdf_bytes)

    imageFilter = ImageFilter()
    filtered_images = await imageFilter.heuristic_filter(images)
    print(len(images))
    print(len(filtered_images))



asyncio.run(main())