from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
from pypdf import PdfReader
from dotenv import load_dotenv
import io

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


client = Anthropic()

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def generate_questions(content: str) -> str:
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are a study assistant. Based on the following content, generate 10 study questions that test understanding of the key concepts and problem-solving skills through applied problems.

Content:
{content}

Format each question clearly and numbered."""
            }
        ]
    )
    return message.content[0].text


@app.post("/generate")
async def generate(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None)
):
    if file:
        file_bytes = await file.read()
        content = extract_text_from_pdf(file_bytes)
    elif text:
        content = text
    else:
        return {"error": "Please provide a PDF or text"}

    if not content.strip():
        return {"error": "Could not extract any text from the file"}

    questions = generate_questions(content)
    return {"questions": questions}