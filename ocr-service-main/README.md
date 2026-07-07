# OCR Service

An intelligent, high-performance Optical Character Recognition (OCR) microservice. This service is designed to extract text, Markdown, and formatted HTML tables from both images and PDF documents.

## Key Highlights

- **Mistral OCR Integration**: Leverages Mistral's state-of-the-art vision models for high-accuracy text extraction and perfect HTML table generation.
- **Fail-Safe Architecture**: Uses a Strategy Pattern to automatically fallback to local PaddleOCR inference if the cloud service is unavailable, ensuring 100% uptime.
- **FastAPI Powered**: Asynchronous, fast, and robust API endpoints.
- **Comprehensive Format Support**: Supports all major image formats and handles both scanned and digital PDFs seamlessly.

## Documentation Navigation

Please refer to the following documents for detailed information:

- [Features (FEATURES.md)](FEATURES.md): Detailed capabilities of the service, including table extraction and intelligent preprocessing.
- [Setup Guide (SETUP.md)](SETUP.md): Instructions on how to install dependencies, configure environment variables, and start the server.
- [Architecture & APIs (ARCHITECTURE.md)](ARCHITECTURE.md): Explanation of the Pluggable Engine Architecture and a complete reference for all REST API endpoints.

## Quick Start

1. Clone the repository.
2. Install requirements using `uv pip install -r requirements.txt`.
3. Set your `MISTRAL_API_KEY` in the `.env` file.
4. Run `uvicorn main:app --host 0.0.0.0 --port 8000`.
5. Access the API documentation at `http://localhost:8000/docs`.
