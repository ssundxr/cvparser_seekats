import os
import json
import fitz  # PyMuPDF
import docx
import google.generativeai as genai
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CV Parser MVP")

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# Define the precise structured output using Pydantic
class Experience(BaseModel):
    company: str
    role: str
    start_date: str
    end_date: str
    description: str

class Education(BaseModel):
    institution: str
    degree: str
    graduation_year: str

class ContactInfo(BaseModel):
    email: Optional[str]
    phone: Optional[str]
    linkedin: Optional[str]
    github: Optional[str]

class CVData(BaseModel):
    name: str = Field(description="Full name of the candidate")
    contact_info: ContactInfo
    education: List[Education]
    experience: List[Experience]
    skills: List[str]

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        doc = fitz.open("pdf", file_bytes)
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {str(e)}")

def extract_text_from_docx(file_bytes: bytes) -> str:
    # docx requires a file-like object
    try:
        from io import BytesIO
        doc = docx.Document(BytesIO(file_bytes))
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        raise ValueError(f"Failed to parse DOCX: {str(e)}")

@app.post("/api/parse-cv")
async def parse_cv(file: UploadFile = File(...)):
    # Check API key inside route so we can show proper error if missing
    current_key = os.getenv("GEMINI_API_KEY")
    if not current_key or current_key == "your_gemini_api_key_here":
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured in .env file.")
    
    # Configure each time since user might update .env while server is running
    genai.configure(api_key=current_key)
    
    content = await file.read()
    filename = file.filename.lower()
    
    if filename.endswith(".pdf"):
        text = extract_text_from_pdf(content)
    elif filename.endswith(".docx"):
        text = extract_text_from_docx(content)
    else:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported.")
        
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from the document. It might be empty or an image-based PDF.")

    # Call Gemini API with structured output
    try:
        # gemini-2.5-flash is fast, extremely accurate, and supports structured JSON outputs wonderfully
        model = genai.GenerativeModel('gemini-2.5-flash',
            generation_config={"response_mime_type": "application/json",
                               "response_schema": CVData}
        )
        prompt = f"""
        Extract the following information from the resume text provided below. 
        Ensure extreme precision and accuracy. If a piece of information is missing, output an empty string or null.
        For skills, extract a comprehensive list of distinct technical and soft skills.
        
        Resume text:
        {text}
        """
        response = model.generate_content(prompt)
        
        # Parse the JSON response
        parsed_data = json.loads(response.text)
        return parsed_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Parsing failed: {str(e)}")

# Mount the static directory
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
