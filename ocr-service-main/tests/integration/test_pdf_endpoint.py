"""Integration tests for POST /ocr/pdf."""
import io


def test_valid_pdf_returns_200(test_client, sample_pdf_bytes):
    response = test_client.post(
        "/ocr/pdf",
        files={"file": ("digital.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert "pages" in data


def test_corrupted_pdf_returns_422(test_client):
    response = test_client.post(
        "/ocr/pdf",
        files={"file": ("bad.pdf", io.BytesIO(b"not a pdf at all"), "application/pdf")},
    )
    assert response.status_code == 422


def test_empty_pdf_returns_422(test_client):
    response = test_client.post(
        "/ocr/pdf",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert response.status_code == 422
