import aiosqlite
import json
from pathlib import Path
from app.config import DB_PATH

_connection: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _connection
    if _connection is None:
        _connection = await aiosqlite.connect(str(DB_PATH))
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA foreign_keys = ON")
        await _connection.executescript(SCHEMA)
        try:
            await _connection.execute("ALTER TABLE projects ADD COLUMN composed_audio TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            await _connection.execute("ALTER TABLE projects ADD COLUMN video_path TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            await _connection.execute("ALTER TABLE projects ADD COLUMN uuid TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        import uuid as _uuid
        rows = await _connection.execute("SELECT id FROM projects WHERE uuid = '' OR uuid IS NULL")
        for row in await rows.fetchall():
            new_uuid = _uuid.uuid4().hex
            await _connection.execute("UPDATE projects SET uuid = ? WHERE id = ?", (new_uuid, row[0]))
        await _connection.commit()
    return _connection


async def close_db():
    global _connection
    if _connection:
        await _connection.close()
        _connection = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    topic TEXT DEFAULT '',
    ppt_filename TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',
    composed_audio TEXT DEFAULT '',
    video_path TEXT DEFAULT '',
    user_id INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    slide_number INTEGER NOT NULL,
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    narration TEXT DEFAULT '',
    narration_audio TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    ref_audio_path TEXT DEFAULT '',
    prompt_text TEXT DEFAULT '',
    embedding_data TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reference_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content TEXT DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""
