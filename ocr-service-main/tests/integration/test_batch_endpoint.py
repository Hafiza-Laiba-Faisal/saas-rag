"""Integration tests for POST /ocr/batch."""
import io


def test_batch_valid_files_returns_200(test_client, sample_image_bytes):
    files = [
        ("files", ("img1.png", io.BytesIO(sample_image_bytes), "image/png")),
        ("files", ("img2.png", io.BytesIO(sample_image_bytes), "image/png")),
    ]
    response = test_client.post("/ocr/batch", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 2
    assert data["successful"] == 2
    assert data["failed"] == 0
