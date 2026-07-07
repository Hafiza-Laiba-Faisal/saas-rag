import os
import sys
import uvicorn
from pathlib import Path


def main():
    # Ensure src directory is in system path so python resolves rbs_rag package
    src_dir = Path(__file__).parent.parent.resolve()
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    print("==========================================================")
    print("   RBS RAG MULTI-TENANT SAAS PLATFORM BACKEND SERVICES    ")
    print("==========================================================")
    print("  -> Admin Dashboard:    http://localhost:8000")
    print("  -> Interactive Docs:    http://localhost:8000/docs")
    print("  -> Embeddable Widget:   http://localhost:8000/widget")
    print("==========================================================")
    print("Starting development server...")
    
    # Run development server
    uvicorn.run("rbs_rag.web.server:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
