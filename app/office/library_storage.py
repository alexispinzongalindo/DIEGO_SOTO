import os
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename


def _allowed_extension(filename: str) -> bool:
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower().strip()
    allowed = set(current_app.config.get('DOCUMENT_LIBRARY_ALLOWED_EXTENSIONS') or [])
    return ext in allowed


def ensure_library_folder() -> str:
    folder = current_app.config.get('DOCUMENT_LIBRARY_FOLDER')
    if not folder:
        folder = os.path.join(current_app.static_folder, 'uploads', 'library')
    Path(folder).mkdir(parents=True, exist_ok=True)
    return folder


def save_uploaded_file(uploaded_file):
    if uploaded_file is None or not getattr(uploaded_file, 'filename', None):
        raise ValueError('No file provided.')

    original = secure_filename(uploaded_file.filename)
    if not _allowed_extension(original):
        raise ValueError('File type not allowed.')

    ext = original.rsplit('.', 1)[1].lower()
    stored = f"{uuid.uuid4().hex}.{ext}"

    folder = ensure_library_folder()
    abs_path = os.path.join(folder, stored)
    uploaded_file.save(abs_path)

    size_bytes = None
    try:
        size_bytes = os.path.getsize(abs_path)
    except Exception:
        pass

    return {
        'original_filename': original,
        'stored_filename': stored,
        'content_type': getattr(uploaded_file, 'mimetype', None),
        'size_bytes': size_bytes,
        'abs_path': abs_path,
    }


def get_document_abs_path(stored_filename: str) -> str:
    folder = ensure_library_folder()
    return os.path.join(folder, stored_filename)


def delete_document_file(stored_filename: str) -> None:
    if not stored_filename:
        return
    abs_path = get_document_abs_path(stored_filename)
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        current_app.logger.exception('Failed to delete document file')
