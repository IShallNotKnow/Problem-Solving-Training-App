from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from anthropic import Anthropic
from pypdf import PdfReader
from dotenv import load_dotenv
import os
import io

load_dotenv()

app = FastAPI()
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


client = Anthropic()

async def get_current_user():
    user = supabase.auth.get_user()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def extract_text_from_pdf(file_bytes: bytes, user=Depends(get_current_user)) -> str:
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

@app.post("/testOutput")
async def test(file: UploadFile):
    file_bytes = await file.read()
    content = extract_text_from_pdf(file_bytes)
    return content


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
    
    document = supabase.table("documents").insert({
        "filename": file.filename if file else "pasted_text",
        "extracted_text": content
    }).execute()
    
    document_id = document.data[0]["id"]

    questions = generate_questions(content)
    
    supabase.table("questions").insert({
        "document_id" : document_id,
        "content" : questions
    }).execute()

    return {"questions": questions}