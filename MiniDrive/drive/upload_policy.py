MAX_UPLOAD_SIZE = 20 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".txt",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".xlsx",
    ".zip",
}

BLOCKED_EXTENSIONS = {".exe", ".bat", ".sh"}

ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/zip",
    "application/x-zip-compressed",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
