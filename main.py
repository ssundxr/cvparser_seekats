import os
import json
import fitz  # PyMuPDF
import docx
import pdfplumber
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
from io import BytesIO
from PIL import Image

# Optional imports with graceful fallback
try:
    import pytesseract
    HAS_OCR = True
except:
    HAS_OCR = False
    print("Warning: pytesseract not available. OCR will be disabled.")

try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
        HAS_SPACY = True
    except OSError:
        nlp = None
        HAS_SPACY = False
        print("Warning: spacy 'en_core_web_sm' model not found. NER pre-processing will be skipped.")
except:
    nlp = None
    HAS_SPACY = False
    print("Warning: spacy not available. NER pre-processing will be skipped.")

try:
    import instructor
    import google.generativeai as genai
    HAS_INSTRUCTOR = True
except:
    import google.generativeai as genai
    HAS_INSTRUCTOR = False
    print("Warning: instructor library not available. Using standard Gemini API.")

load_dotenv()

app = FastAPI(title="CV Parser MVP")

# Define the precise structured output using Pydantic
class Experience(BaseModel):
    company: str = Field(description="Name of the company or organization")
    role: str = Field(description="Job title or role")
    start_date: str = Field(description="Start date of the role (e.g. Jan 2020)")
    end_date: str = Field(description="End date of the role. Use 'Present' or 'Current' if still working there.")
    description: str = Field(description="Detailed summary of responsibilities and achievements")

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

def extract_entities(text: str) -> dict:
    """Uses NLP to extract ORG, PERSON, and GPE entities as hints for the LLM."""
    if not HAS_SPACY or not nlp:
        return {"ORG": [], "PERSON": [], "GPE": []}
    
    # Process the first 10,000 characters to avoid huge CPU overhead on large docs
    doc = nlp(text[:10000])
    entities = {"ORG": set(), "PERSON": set(), "GPE": set()}
    
    for ent in doc.ents:
        if ent.label_ in entities:
            # Clean up newlines in entity text
            entities[ent.label_].add(ent.text.replace("\n", " ").strip())
            
    # Limit to top 15 distinct entities per category to prevent prompt bloating
    return {k: list(v)[:15] for k, v in entities.items()}

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extracts text using pdfplumber for layout, with OCR fallback."""
    text = ""
    
    # Strategy 1: Layout-aware extraction with pdfplumber
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                # layout=True preserves visual columns and tables better than standard extraction
                page_text = page.extract_text(layout=True)
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"pdfplumber failed: {e}")
        pass

    # Strategy 2: OCR Fallback if text is unusually sparse (e.g. < 50 chars indicates an image PDF)
    if len(text.strip()) < 50:
        if not HAS_OCR:
            raise ValueError("Document appears to be scanned/image-based but OCR (pytesseract) is not available.")
        
        print("Scanned document detected. Initiating OCR fallback...")
        text = ""
        try:
            doc = fitz.open("pdf", file_bytes)
            for page in doc:
                # Render page to an image
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Perform OCR
                page_text = pytesseract.image_to_string(img)
                text += page_text + "\n"
        except Exception as e:
            raise ValueError(f"Failed to perform OCR on PDF: {str(e)}")

    if not text.strip():
        raise ValueError("Document appears to be entirely empty or unreadable.")

    return text

def extract_text_from_docx(file_bytes: bytes) -> str:
    # docx requires a file-like object
    try:
        doc = docx.Document(BytesIO(file_bytes))
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        raise ValueError(f"Failed to parse DOCX: {str(e)}")

@app.post("/api/parse-cv")
async def parse_cv(file: UploadFile = File(...), api_key: str = Form(...)):
    # Check API key inside route so we can show proper error if missing
    current_key = api_key.strip() if api_key else ""
    if not current_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is required.")
    
    # Configure each time with user's key
    genai.configure(api_key=current_key)
    
    content = await file.read()
    filename = file.filename.lower()
    
    if filename.endswith(".pdf"):
        try:
            text = extract_text_from_pdf(content)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
    elif filename.endswith(".docx"):
        try:
            text = extract_text_from_docx(content)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
    else:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported.")
        
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from the document. It might be empty or an image-based PDF.")

    # 1. NLP Pre-processing: Identify named entities for context
    entities = extract_entities(text)
    entity_context = f"""
    [Hints from NLP Pre-processing]
    Organizations/Companies found: {', '.join(entities['ORG']) if entities['ORG'] else 'None identified'}
    Locations found: {', '.join(entities['GPE']) if entities['GPE'] else 'None identified'}
    People found: {', '.join(entities['PERSON']) if entities['PERSON'] else 'None identified'}
    """

    # Call Gemini API with or without Instructor for Structured Output
    try:
        if HAS_INSTRUCTOR:
            # Use instructor for guaranteed structured output
            base_model = genai.GenerativeModel('gemini-2.5-flash')
            client = instructor.from_gemini(
                client=base_model,
                mode=instructor.Mode.GEMINI_JSON
            )
            
            prompt = f"""
            Extract the following information from the resume text provided below. 
            Ensure extreme precision and accuracy. If a piece of information is missing, output an empty string or null.
            For skills, extract a comprehensive list of distinct technical and soft skills.
            
            {entity_context}
            
            Resume text:
            {text}
            """

            # Using Instructor to enforce the CVData schema directly
            parsed_data = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                response_model=CVData,
                max_retries=3
            )
            
            return parsed_data.model_dump()
        else:
            # Use standard Gemini API with JSON mode
            model = genai.GenerativeModel(
                'gemini-2.5-flash',
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "contact_info": {
                                "type": "object",
                                "properties": {
                                    "email": {"type": "string"},
                                    "phone": {"type": "string"},
                                    "linkedin": {"type": "string"},
                                    "github": {"type": "string"}
                                }
                            },
                            "education": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "institution": {"type": "string"},
                                        "degree": {"type": "string"},
                                        "graduation_year": {"type": "string"}
                                    }
                                }
                            },
                            "experience": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "company": {"type": "string"},
                                        "role": {"type": "string"},
                                        "start_date": {"type": "string"},
                                        "end_date": {"type": "string"},
                                        "description": {"type": "string"}
                                    }
                                }
                            },
                            "skills": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["name", "contact_info", "education", "experience", "skills"]
                    }
                }
            )
            
            prompt = f"""
            Extract the following information from the resume text provided below and return it as JSON.
            Ensure extreme precision and accuracy. If a piece of information is missing, use empty string or empty array.
            For skills, extract a comprehensive list of distinct technical and soft skills.
            
            {entity_context}
            
            Resume text:
            {text}
            """
            
            response = model.generate_content(prompt)
            return json.loads(response.text)
        
    except Exception as e:
        print(f"AI Parsing error detail: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI Parsing failed: {str(e)}")

# Mount the static directory
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
