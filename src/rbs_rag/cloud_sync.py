from __future__ import annotations

import hashlib
import json
import re
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm", ".xlsx", ".xls", ".csv", ".pptx"}

# Google Docs MIME types that require export (not direct download)
GOOGLE_APPS_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "application/vnd.google-apps.spreadsheet": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "application/vnd.google-apps.presentation": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "application/vnd.google-apps.drawing": ("pdf", "application/pdf"),
}


CLOUD_PROVIDER_PREFIXES = {
    "google_drive": "cloud_gdrive_",
    "gdrive": "cloud_gdrive_",
    "drive": "cloud_gdrive_",
    "onedrive": "cloud_onedrive_",
    "1drive": "cloud_onedrive_",
    "s3": "cloud_s3_",
    "url": "cloud_url_",
    "direct": "cloud_url_",
    "http": "cloud_url_",
}


def sync_cloud_documents(
    tenant_id: str,
    tenants_dir: Path,
    provider: str,
    cloud_url_or_id: str,
    api_key_or_token: str | None = None,
    custom_filename: str | None = None,
) -> dict[str, Any]:
    """
    Downloads documents from cloud sources directly and exclusively into the tenant's isolated directory:
    .rbs_rag/tenants/{tenant_id}/documents/
    Files are prefixed with cloud_{provider}_ for tracking in the UI.
    """
    # Strict path isolation
    tenant_docs_dir = tenants_dir / tenant_id / "documents"
    tenant_docs_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files: list[Path] = []
    errors: list[str] = []

    # Resolve the prefix for renaming
    raw_provider = provider.lower().strip()
    file_prefix = CLOUD_PROVIDER_PREFIXES.get(raw_provider, "cloud_unknown_")

    if raw_provider in {"google_drive", "gdrive", "drive"}:
        downloaded_files, errors = download_from_google_drive(cloud_url_or_id, tenant_docs_dir, api_key_or_token, file_prefix=file_prefix)
    elif raw_provider in {"onedrive", "1drive"}:
        downloaded_files, errors = download_from_onedrive(cloud_url_or_id, tenant_docs_dir, api_key_or_token, file_prefix=file_prefix)
    elif raw_provider in {"url", "s3", "direct", "http"}:
        downloaded_files, errors = download_from_direct_url(cloud_url_or_id, tenant_docs_dir, custom_filename, file_prefix=file_prefix)
    else:
        errors.append(f"Unsupported cloud provider: '{provider}'. Supported: google_drive, onedrive, url/direct.")

    file_names = [f.name for f in downloaded_files]
    return {
        "status": "success" if downloaded_files and not errors else ("partial" if downloaded_files else "error"),
        "tenant_id": tenant_id,
        "downloaded": file_names,
        "count": len(file_names),
        "errors": errors,
    }


def parse_google_drive_id(url_or_id: str) -> tuple[str, str]:
    """Returns (id_type, extracted_id) where id_type is 'file' or 'folder'."""
    text = url_or_id.strip()

    # Folder pattern: /folders/FOLDER_ID
    folder_match = re.search(r"/folders/([a-zA-Z0-9_-]+)", text)
    if folder_match:
        return "folder", folder_match.group(1)

    # File pattern: /file/d/FILE_ID or id=FILE_ID
    file_match = re.search(r"/d/([a-zA-Z0-9_-]+)", text) or re.search(r"id=([a-zA-Z0-9_-]+)", text)
    if file_match:
        return "file", file_match.group(1)

    # Raw ID fallback
    return "file", text


def download_from_google_drive(
    url_or_id: str, dest_dir: Path, api_key_or_token: str | None = None, file_prefix: str = ""
) -> tuple[list[Path], list[str]]:
    downloaded: list[Path] = []
    errors: list[str] = []

    id_type, target_id = parse_google_drive_id(url_or_id)

    if id_type == "folder":
        # Strategy 1: If Google API Key provided, use Drive API v3
        if api_key_or_token and api_key_or_token.startswith("AIza"):
            try:
                api_url = (
                    f"https://www.googleapis.com/drive/v3/files"
                    f"?q='{target_id}'+in+parents+and+trashed=false"
                    f"&fields=files(id,name,mimeType)"
                    f"&key={api_key_or_token}"
                )
                req = urllib.request.Request(api_url, headers={"User-Agent": "TenBit-RAG-CloudSync/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    files = data.get("files", [])
                    if not files:
                        errors.append(f"No accessible files found in Google Drive folder '{target_id}' via API.")
                    for item in files:
                        dl, err = _download_or_export_gdrive_item(
                            item["id"], item["name"], item.get("mimeType", ""), dest_dir, api_key_or_token, file_prefix=file_prefix
                        )
                        downloaded.extend(dl)
                        errors.extend(err)
                    return downloaded, errors
            except Exception as exc:
                errors.append(f"Google Drive API Error: {exc}. Falling back to public HTML scraping.")

        # Strategy 2: Scrape public folder HTML page to extract file items
        try:
            folder_files = _scrape_public_folder_files(target_id)
            if not folder_files:
                errors.append(
                    f"No files could be extracted from public folder '{target_id}'. "
                    f"Ensure the folder is shared as 'Anyone with the link' with at least Viewer access."
                )
            for item in folder_files:
                dl, err = _download_or_export_gdrive_item(
                    item["id"], item["name"], item.get("mime", ""), dest_dir, api_key_or_token, file_prefix=file_prefix
                )
                downloaded.extend(dl)
                errors.extend(err)
        except Exception as exc:
            tb = traceback.format_exc()
            errors.append(f"Google Drive Folder Scrape Error: {exc}\nTraceback:\n{tb}")

    else:
        # Single file download
        dl, err = _download_or_export_gdrive_item(target_id, None, "", dest_dir, api_key_or_token, file_prefix=file_prefix)
        downloaded.extend(dl)
        errors.extend(err)

    return downloaded, errors


def _scrape_public_folder_files(folder_id: str) -> list[dict[str, str]]:
    """
    Scrape the public Google Drive folder HTML page to extract file IDs, names, and MIME types.
    Google Drive embeds file metadata in AF_initDataCallback JSON payloads.
    """
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    files: list[dict[str, str]] = []

    # Parse AF_initDataCallback blocks for file metadata
    callbacks = re.findall(r'AF_initDataCallback\s*\(\s*({.*?})\s*\)\s*;', html, re.DOTALL)
    for cb in callbacks:
        data_match = re.search(r'data\s*:\s*(.*)\s*,\s*sideChannel', cb, re.DOTALL)
        if not data_match:
            continue
        try:
            data_obj = json.loads(data_match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue

        # Recursively search for file item tuples:
        # Structure: [null, "FILE_ID"], ..., "application/...", ..., [["Email", ...]]
        _extract_drive_items(data_obj, files, folder_id)

    # Deduplicate by file ID
    seen = set()
    unique_files = []
    for f in files:
        if f["id"] not in seen:
            seen.add(f["id"])
            unique_files.append(f)

    return unique_files


def _extract_drive_items(node: Any, results: list[dict], folder_id: str) -> None:
    """Recursively walk the parsed JSON tree looking for Drive file item arrays."""
    if not isinstance(node, list):
        return

    # Check if this node matches: [null, "FILE_ID"] pattern at index 0
    # followed by mime type at index 4
    if (
        len(node) > 5
        and isinstance(node[0], list)
        and len(node[0]) >= 2
        and node[0][0] is None
        and isinstance(node[0][1], str)
        and len(node[0][1]) >= 20
        and isinstance(node[4], str)
        and ("application/" in node[4] or "text/" in node[4] or "image/" in node[4] or "video/" in node[4])
    ):
        file_id = node[0][1]
        mime_type = node[4]

        # Skip the folder itself
        if file_id == folder_id:
            return

        # Try to extract filename from nested structure
        name = _extract_name_from_item(node)
        if not name:
            # Fallback name from mime type
            ext = _mime_to_extension(mime_type)
            name = f"gdrive_{file_id[:10]}.{ext}"

        results.append({"id": file_id, "name": name, "mime": mime_type})
        return

    # Recurse into child arrays
    for child in node:
        if isinstance(child, list):
            _extract_drive_items(child, results, folder_id)


def _extract_name_from_item(node: Any) -> str | None:
    """Try to extract the file's display name from deep nested arrays."""
    if not isinstance(node, list):
        return None

    # Walk looking for a string that looks like a filename (not a URL, not a mime type)
    all_strings = []

    def _collect(n: Any, depth: int = 0) -> None:
        if depth > 15:
            return
        if isinstance(n, str) and len(n) > 0:
            all_strings.append(n)
        elif isinstance(n, list):
            for child in n:
                _collect(child, depth + 1)

    _collect(node)

    # Filter: look for strings that are plausible filenames
    for s in all_strings:
        if (
            not s.startswith("http")
            and not s.startswith("//")
            and "application/" not in s
            and "vnd." not in s
            and "google-apps" not in s
            and "Google" not in s
            and len(s) > 1
            and len(s) < 200
            and s not in {"Shared", "Download", "Modified", "Size", "Name"}
            and not s.startswith("driveweb")
            and not re.match(r'^\d+ [A-Z][a-z]+ \d{4}$', s)  # e.g. "9 Sept 2025"
            and not re.match(r'^\d+ [A-Z]B$', s)  # e.g. "5 KB"
            and "Storage used" not in s
        ):
            return s

    return None


def _mime_to_extension(mime: str) -> str:
    """Map a MIME type to a file extension."""
    mime_map = {
        "application/pdf": "pdf",
        "application/vnd.google-apps.document": "docx",
        "application/vnd.google-apps.spreadsheet": "xlsx",
        "application/vnd.google-apps.presentation": "pptx",
        "application/vnd.google-apps.drawing": "pdf",
        "text/plain": "txt",
        "text/html": "html",
        "text/markdown": "md",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    }
    return mime_map.get(mime, "pdf")


def _download_or_export_gdrive_item(
    file_id: str,
    name: str | None,
    mime_type: str,
    dest_dir: Path,
    token_or_key: str | None,
    file_prefix: str = "",
) -> tuple[list[Path], list[str]]:
    """Download a single Google Drive file. Handles Google Docs export."""
    downloaded: list[Path] = []
    errors: list[str] = []

    # If it's a Google Apps native type (Google Docs/Sheets/Slides), export it
    if mime_type in GOOGLE_APPS_EXPORT_MAP:
        ext, export_mime = GOOGLE_APPS_EXPORT_MAP[mime_type]
        safe_name = name or f"gdrive_{file_id[:10]}"
        # Strip existing extension if any
        if "." in safe_name:
            safe_name = safe_name.rsplit(".", 1)[0]
        target_name = f"{file_prefix}{safe_name}.{ext}"
        dest_path = _sanitize_dest_path(dest_dir, target_name)

        export_url = f"https://docs.google.com/document/d/{file_id}/export?format={ext}"
        if "spreadsheet" in mime_type:
            export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format={ext}"
        elif "presentation" in mime_type:
            export_url = f"https://docs.google.com/presentation/d/{file_id}/export?format={ext}"
        elif "drawing" in mime_type:
            export_url = f"https://docs.google.com/drawings/d/{file_id}/export/pdf"

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if token_or_key and not token_or_key.startswith("AIza"):
            headers["Authorization"] = f"Bearer {token_or_key}"

        try:
            req = urllib.request.Request(export_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()
                if len(content) > 100:
                    dest_path.write_bytes(content)
                    downloaded.append(dest_path)
                else:
                    errors.append(f"Empty or too-small export response for '{safe_name}' ({file_id}).")
        except Exception as exc:
            errors.append(f"Google Docs Export Error for '{safe_name}' ({file_id}): {exc}")

        return downloaded, errors

    # Regular binary file download
    safe_name = name or f"gdrive_{file_id[:12]}.pdf"
    safe_name = f"{file_prefix}{safe_name}" if file_prefix and not safe_name.startswith(file_prefix) else safe_name
    dest_path = _sanitize_dest_path(dest_dir, safe_name)
    success = _download_gdrive_single_file(file_id, dest_path, token_or_key)
    if success:
        downloaded.append(dest_path)
    else:
        errors.append(f"Failed to download Google Drive file '{safe_name}' ({file_id}). Check sharing permissions.")

    return downloaded, errors


def _download_gdrive_single_file(file_id: str, dest_path: Path, token_or_key: str | None = None) -> bool:
    urls_to_try = [
        f"https://drive.google.com/uc?export=download&id={file_id}",
        f"https://docs.google.com/uc?export=download&confirm=t&id={file_id}",
    ]
    if token_or_key:
        if token_or_key.startswith("AIza"):
            urls_to_try.insert(0, f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={token_or_key}")
        else:
            urls_to_try.insert(0, f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    if token_or_key and not token_or_key.startswith("AIza"):
        headers["Authorization"] = f"Bearer {token_or_key}"

    for download_url in urls_to_try:
        try:
            req = urllib.request.Request(download_url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                content = resp.read()
                if len(content) > 100 and b"google.com/accounts" not in content[:2000]:
                    dest_path.write_bytes(content)
                    return True
        except Exception:
            continue
    return False


def download_from_onedrive(
    url_or_link: str, dest_dir: Path, access_token: str | None = None, file_prefix: str = ""
) -> tuple[list[Path], list[str]]:
    downloaded: list[Path] = []
    errors: list[str] = []

    link = url_or_link.strip()
    if "sharepoint.com" in link or "1drv.ms" in link or "onedrive.live.com" in link:
        if "download=1" not in link and "?" in link:
            download_url = link + "&download=1"
        elif "download=1" not in link:
            download_url = link + "?download=1"
        else:
            download_url = link

        filename = f"{file_prefix}onedrive_doc.pdf"
        files, errs = download_from_direct_url(download_url, dest_dir, filename_override=filename, file_prefix=file_prefix)
        downloaded.extend(files)
        errors.extend(errs)
    else:
        errors.append(
            "Invalid OneDrive URL. Must be a sharepoint.com, 1drv.ms, or onedrive.live.com share link."
        )

    return downloaded, errors


def download_from_direct_url(
    url: str, dest_dir: Path, filename_override: str | None = None, file_prefix: str = ""
) -> tuple[list[Path], list[str]]:
    downloaded: list[Path] = []
    errors: list[str] = []

    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        errors.append(f"Invalid URL protocol for '{url}'. Must start with http:// or https://")
        return downloaded, errors

    try:
        parsed_url = urllib.parse.urlparse(url)
        path_name = Path(parsed_url.path).name
        if filename_override:
            target_name = filename_override
        elif path_name and Path(path_name).suffix.lower() in SUPPORTED_EXTENSIONS:
            target_name = f"{file_prefix}{path_name}" if file_prefix else path_name
        else:
            target_name = f"{file_prefix}cloud_doc_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}.pdf"

        dest_path = _sanitize_dest_path(dest_dir, target_name)

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()
            if not content:
                errors.append(f"Empty response received from '{url}'.")
                return downloaded, errors
            dest_path.write_bytes(content)
            downloaded.append(dest_path)

    except Exception as exc:
        errors.append(f"HTTP Download Error ({url}): {exc}")

    return downloaded, errors


def _sanitize_dest_path(dest_dir: Path, filename: str) -> Path:
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", filename).strip()
    if not safe_name:
        safe_name = "synced_document.pdf"
    if not Path(safe_name).suffix:
        safe_name += ".pdf"
    return dest_dir / safe_name
