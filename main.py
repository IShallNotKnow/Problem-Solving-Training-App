from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
from llama_cloud import AsyncLlamaCloud
import tempfile
from dotenv import load_dotenv
import os
from pathlib import Path
import asyncio
import httpx
import base64
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
                "images_to_save": ["layout", "embedded"],
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
        self.exclude_types = {"logo", "icon", "banner", "header", "footer"}
        self.client = Anthropic()
    
    async def heuristic_filter(self, images: list) -> list:
        if not images:
            return None
        
        filtered = []
        for image in images:
            width = image["bbox"]["w"]
            height = image["bbox"]["h"]
            if image["content_type"] in self.exclude_types or height < 100 or width < 100:
                continue

            aspect_ratio = width/height
            if aspect_ratio > 10 or aspect_ratio < 0.1:
                continue

            filtered.append(image)
        
        return filtered
    
    async def semantic_filter(self, images: list, markdown: str) -> tuple[list[dict], dict[str, str]]:
        if not images:
            return []

        final_images = []
        descriptions = {}

        async with httpx.AsyncClient() as http_client:
            for image in images:
                try:
                    img_response = await http_client.get(image["url"])
                    if img_response.status_code != 200:
                        continue

                    base64_image = base64.b64encode(img_response.content).decode("utf-8")

                    result = self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=500,
                        temperature=0.0,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": image.get("content_type", "image/png"),
                                            "data": base64_image
                                        }
                                    },
                                    {
                                        "type": "text",
                                        "text": f"""Analyze these images from a lecture PDF.
First line: YES if it contains academically meaningful content (diagram, graph, 
mathematical figure, chart, technical illustration), NO if decorative or irrelevant.

If YES, second line onward: describe the academic content concisely, including any 
text, labels, or mathematical notation visible that may not appear in the lecture notes. 
If NO, stop after the first line."""
                                    }
                                ]
                            }
                        ]
                    )

                    response_text = result.content[0].text.strip()
                    first_line = response_text.split("\n")[0].upper()

                    if first_line == "YES":
                        final_images.append(image)

                        if "\n" in response_text:
                            descriptions[image["filename"]] = response_text.split("\n", 1)[1].strip()

                except Exception as e:
                    print(f"Error filtering image {image.get('filename')}: {e}")
                    final_images.append(image)  # keep on error, better to include than lose

        return final_images, descriptions


class TextFilter:
    def __init__(self):
        self.keep_types = {
            "paragraph", "heading", "equation", "table", "figure_caption", "list", "text", "code"
        }
    
    async def item_filter(self, items: list) -> list:
        if not items:
            return None

        return [item for item in items if item["type"] in self.keep_types]

class ConceptExtractor:
    def __init__(self):
        self.CONCEPT_SIGNALS = {
            "heading": 1.0,   # high signal
            "figure_caption": 0.8,
            "list": 0.7, #likely useful?, lists could denote purposes, code, etc. 
            "equation": 0.9,
            "code": 0.9,
            "table": 0.7,
            "paragraph": 0.3, # low signal individually, high in context
            "text": 0.2 #could be very informational, but too broad of a category
        }

        self.ALWAYS_INCLUDE = {"heading", "equation", "theorem", "definition", "code", "table"}


    async def score_pages(self, items: list) -> dict:
        page_scores = {}
        
        for item in items:
            page = item["page"]
            item_type = item.get("type", "")
            weight = self.CONCEPT_SIGNALS.get(item_type, 0)
            page_scores[page] = page_scores.get(page, 0) + weight
        
        return page_scores
    
    async def prioritize_content(self, items: list, page_scores: dict) -> str:
        sorted_pages = sorted(page_scores, key=page_scores.get, reverse=True)

        result = []
        for page in sorted_pages:
            page_items = [i for i in items if i["page"] == page]
            score = page_scores[page]

            has_priority_item = any(
                i.get("type") in self.ALWAYS_INCLUDE
                for i in page_items
            )

            if score > 3.0 or has_priority_item:
                page_text = "\n".join(i["md"] for i in page_items if i.get("md"))
                label = "[HIGH PRIORITY]" if score > 3.0 else "[CONTAINS KEY CONTENT]"
                result.append(f"{label} page {page}\n{page_text}")

        return "\n\n".join(result)

class QuestionGenerator:
    def __init__(self):
        self.client = Anthropic()

    async def build_images(self, image: dict):
        async with httpx.AsyncClient() as http_client:
            try:
                img_response = await http_client.get(image["url"])
                if img_response.status_code != 200:
                    return None

                base64_image = base64.b64encode(img_response.content).decode("utf-8")

                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.get("content_type", "image/png"),
                        "data": base64_image
                    }
                },
            
            except Exception as e:
                print(f"Error filtering image {image.get('filename')}: {e}")
                return None


    async def generate_questions(self, content: str, images: list, image_descriptions: dict) -> str:
        message_content = [
            {
                "type": "text",
                "text": f"""
    You are a study assistant.

    Based on the following content and images, generate 20 study questions
    (10 MCQ, 10 FRQ) that test understanding of the key concepts and
    problem-solving skills.

    Content:
    {content}

    Image Descriptions:
    """
            }
        ]

        image_blocks = await asyncio.gather(
            *(self.build_images(img) for img in images)
        )

        for i, (image, image_block) in enumerate(zip(images, image_blocks), start=1):
            description = image_descriptions.get(image["filename"])
            if image_block is not None:
                message_content.append(image_block)

            if description:
                message_content.append(
                    {
                        "type": "text",
                        "text": f"Image {i} description:\n{description}"
                    }
                )

        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": message_content,
                }
            ],
        )
        
        return message.content[0].text

class QuestionValidator:
    def __init__(self):
        self.client = Anthropic()
        self.questionGenerator = QuestionGenerator()
    
    async def validate_questions(self, questions: str):
        if not questions:
            return None
        
        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": f"""
{questions}
"""
                }
            ]
        )

        ...
    



async def main():
    pdf_bytes = Path("test_files/002-shortest-paths-1.pdf").read_bytes()

    processor = AsyncPDFProcessor()
    markdown, items, images = await processor.extract(pdf_bytes)

    imageFilter = ImageFilter()
    filtered_images = await imageFilter.heuristic_filter(images)

    # print(len(images))
    # print(len(filtered_images))
    # print([image["url"] for image in filtered_images])
    
    textFilter = TextFilter()
    filtered_items = await textFilter.item_filter(items)

    # print(len(items))
    # print(len(filtered_items))

    # print([item for item in items if item not in filtered_items])
    # print([item for item in items if item.get("type") == "handwriting"])

    conceptExtractor = ConceptExtractor()
    scored_pages = await conceptExtractor.score_pages(filtered_items)
    prompt_str = await conceptExtractor.prioritize_content(filtered_items, scored_pages)

    # print(scored_pages)
    # print(prompt_str)


asyncio.run(main())