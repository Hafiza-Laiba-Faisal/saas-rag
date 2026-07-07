"""Integration tests for POST /ocr/image."""
import io


def test_valid_png_returns_200(test_client, sample_image_bytes):
    response = test_client.post(
        "/ocr/image",
        files={"file": ("sample.png", io.BytesIO(sample_image_bytes), "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert "pages" in data
    assert len(data["pages"]) == 1


def test_unsupported_format_returns_422(test_client):
    response = test_client.post(
        "/ocr/image",
        files={"file": ("test.gif", io.BytesIO(b"GIF89a\x00"), "image/gif")},
    )
    assert response.status_code == 422


def test_empty_file_returns_422(test_client):
    response = test_client.post(
        "/ocr/image",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )
    assert response.status_code == 422


def test_oversized_file_returns_413(test_client):
    big_data = b"x" * (11 * 1024 * 1024)
    response = test_client.post(
        "/ocr/image",
        files={"file": ("big.png", io.BytesIO(big_data), "image/png")},
    )
    assert response.status_code == 413
