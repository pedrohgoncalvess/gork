import httpx


TEMP_FILE_UPLOAD_URL = "https://tmpfile.link/api/upload"


async def upload_temporary_file(
    content: bytes,
    filename: str,
    mime_type: str,
) -> str:
    """Upload bytes anonymously and return the temporary direct HTTPS URL."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TEMP_FILE_UPLOAD_URL,
            files={"file": (filename, content, mime_type)},
        )
    response.raise_for_status()
    download_url = response.json().get("downloadLink")
    if not isinstance(download_url, str) or not download_url.startswith("https://"):
        raise RuntimeError("Temporary upload returned no direct HTTPS download link")
    return download_url
