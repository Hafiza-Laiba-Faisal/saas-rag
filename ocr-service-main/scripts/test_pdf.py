import sys
import json
import asyncio
from config.settings import get_settings
from ocr.engines.mistral_engine import MistralOCREngine
from ocr.engines.paddle_engine import PaddleOCREngine

def test_mistral(file_bytes, filename):
    settings = get_settings()
    engine = MistralOCREngine(api_key=settings.mistral_api_key)
    if not engine.is_available():
        print("Mistral is not available!")
        return
    
    print("Running Mistral OCR...")
    pages = engine.process_pdf(file_bytes, filename)
    with open("mistral_pdf_output.json", "w") as f:
        json.dump([p.model_dump() for p in pages], f, indent=4)
    print(f"Mistral OCR completed. Found {len(pages)} pages.")

def test_paddle(file_bytes, filename):
    settings = get_settings()
    langs = [lang.strip() for lang in settings.ocr_languages.split(",")]
    engine = PaddleOCREngine(languages=langs, use_gpu=settings.use_gpu)
    if not engine.is_available():
        print("PaddleOCR is not available!")
        return
    
    print("Running Paddle OCR...")
    pages = engine.process_pdf(file_bytes, filename)
    with open("paddle_pdf_output.json", "w") as f:
        json.dump([p.model_dump() for p in pages], f, indent=4)
    print(f"Paddle OCR completed. Found {len(pages)} pages.")

def main():
    filepath = "/home/tenbitsolutions/Downloads/ocr-testing/tables.pdf"
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    
    test_mistral(file_bytes, "tables.pdf")
    test_paddle(file_bytes, "tables.pdf")

if __name__ == "__main__":
    main()
