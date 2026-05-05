import os
import uuid
import json
from datetime import datetime
import asyncio
from typing import Dict, Any, Optional

from fastapi import APIRouter, File, UploadFile, Request, HTTPException, Depends
from app.middleware.auth import get_security_context
from app.security.context import SecurityContext
from fastapi.responses import JSONResponse
import pandas as pd

from app.database.manager import DatabaseManager
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

UPLOAD_DIR = "storage/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

# ─── Schema ──────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_uploads (
    id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(50),
    filename VARCHAR(255) NOT NULL,
    parquet_path VARCHAR(500) NOT NULL,
    sheet_names JSONB DEFAULT '[]',
    row_count INT NOT NULL DEFAULT 0,
    schema_json JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'processing',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')
);
CREATE INDEX IF NOT EXISTS idx_uploads_session ON document_uploads(session_id);
CREATE INDEX IF NOT EXISTS idx_uploads_user ON document_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_uploads_expires ON document_uploads(expires_at);
"""

# Columns that may be missing from older table versions.
# ALTER TABLE ADD COLUMN IF NOT EXISTS is idempotent.
_COLUMN_MIGRATIONS = [
    "ALTER TABLE document_uploads ADD COLUMN IF NOT EXISTS session_id VARCHAR(50)",
    "ALTER TABLE document_uploads ADD COLUMN IF NOT EXISTS sheet_names JSONB DEFAULT '[]'",
    "ALTER TABLE document_uploads ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'processing'",
    "ALTER TABLE document_uploads ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE document_uploads ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')",
    "CREATE INDEX IF NOT EXISTS idx_uploads_expires ON document_uploads(expires_at)",
]


async def init_metadata_table(db_manager: DatabaseManager):
    """Create document_uploads table and ensure schema is up to date."""
    pool = db_manager.get_pool("postgres")
    if not pool:
        logger.error("postgres_pool_missing_for_uploads")
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            # Ensure any columns added in later versions exist
            for ddl in _COLUMN_MIGRATIONS:
                await conn.execute(ddl)
        logger.info("document_uploads_table_ready")
    except Exception as e:
        logger.error("create_document_uploads_table_failed", error=str(e))



# ─── Background Conversion ───────────────────────────────────────────────────

def _sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Lowercase + snake_case column names.
    Detects and resolves duplicates that result from sanitization by suffixing _2, _3…
    """
    seen: dict[str, int] = {}
    new_cols = []
    for col in df.columns:
        sanitized = (
            str(col)
            .lower()
            .strip()
            .replace(" ", "_")
            .replace("\n", "_")
            .replace("-", "_")
            .replace(".", "_")
            .replace("/", "_")
        )
        # strip runs of underscores
        while "__" in sanitized:
            sanitized = sanitized.replace("__", "_")
        sanitized = sanitized.strip("_") or "col"

        if sanitized in seen:
            seen[sanitized] += 1
            new_cols.append(f"{sanitized}_{seen[sanitized]}")
        else:
            seen[sanitized] = 1
            new_cols.append(sanitized)

    df.columns = new_cols
    return df


def _infer_schema(df: pd.DataFrame) -> dict:
    """
    Infer a human-readable schema from a DataFrame.
    Handles dates that pandas reads as object dtype (tries parse).
    """
    schema = {}
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        if "int" in dtype_str or "float" in dtype_str:
            schema[col] = "numeric"
        elif "datetime" in dtype_str:
            schema[col] = "datetime"
        elif dtype_str == "object":
            # Try to detect date columns stored as strings
            sample = df[col].dropna().head(20)
            date_count = 0
            for val in sample:
                try:
                    pd.to_datetime(str(val), infer_datetime_format=True)
                    date_count += 1
                except Exception:
                    pass
            if date_count >= len(sample) * 0.8 and len(sample) > 0:
                schema[col] = "datetime"
            else:
                schema[col] = "text"
        else:
            schema[col] = "text"
    return schema


async def process_excel_to_parquet(
    temp_path: str,
    original_filename: str,
    upload_id: str,
    user_id: str,
    session_id: Optional[str],
    db_manager: DatabaseManager,
):
    """
    Background task: converts Excel (all sheets) to a single Parquet with
    a _sheet discriminator column, then persists metadata to Postgres.
    Updates status to 'ready' on success or 'error' on failure.
    """
    logger.info("process_excel_start", upload_id=upload_id, filename=original_filename)

    def _convert() -> tuple[int, dict, list, str]:
        xl = pd.ExcelFile(temp_path)
        try:
            sheet_names = xl.sheet_names

            dfs = []
            for sheet in sheet_names:
                df_sheet = xl.parse(sheet)
                # Drop completely empty rows & columns Excel loves to leave behind
                df_sheet.dropna(how="all", inplace=True)
                df_sheet.dropna(axis=1, how="all", inplace=True)
                df_sheet = _sanitize_columns(df_sheet)
                df_sheet.insert(0, "_sheet", sheet)
                dfs.append(df_sheet)
        finally:
            xl.close()  # Release file handle (required on Windows)

        # Merge all sheets — align columns, fill missing with NaN
        df = pd.concat(dfs, ignore_index=True, sort=False)

        # Drop unnamed index columns pandas may create (unnamed:_0, etc.)
        drop_cols = [c for c in df.columns if c.startswith("unnamed")]
        if drop_cols:
            df.drop(columns=drop_cols, inplace=True)

        # ── DEBUG: Print column structure + first rows to console ─────
        print(f"\n{'='*60}")
        print(f"UPLOAD DEBUG — {original_filename}")
        print(f"Sheets: {sheet_names}  |  Total rows: {len(df)}  |  Columns: {len(df.columns)}")
        print(f"Columns: {list(df.columns)}")
        print(f"Dtypes:\n{df.dtypes}")
        print(f"\ndf.head():\n{df.head().to_string()}")
        print(f"{'='*60}\n")

        # Coerce mixed-type object columns to string for pyarrow.
        # Preserves actual NaN/None as None (not the string "nan").
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].where(df[col].isna(), df[col].astype(str))

        schema = _infer_schema(df)
        parquet_path = os.path.join(UPLOAD_DIR, f"{upload_id}.parquet")
        df.to_parquet(parquet_path, engine="pyarrow", index=False)

        return len(df), schema, sheet_names, parquet_path

    pool = db_manager.get_pool("postgres")
    try:
        row_count, schema, sheet_names, parquet_path = await asyncio.to_thread(_convert)

        if pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE document_uploads
                    SET status='ready', row_count=$1, schema_json=$2,
                        sheet_names=$3, parquet_path=$4
                    WHERE id=$5
                    """,
                    row_count,
                    json.dumps(schema),
                    json.dumps(sheet_names),
                    parquet_path,
                    upload_id,
                )
        logger.info(
            "process_excel_success",
            upload_id=upload_id,
            rows=row_count,
            sheets=sheet_names,
        )

    except Exception as e:
        logger.error("process_excel_failed", upload_id=upload_id, error=str(e))
        # Persist error so the status endpoint surfaces it
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE document_uploads SET status='error', error_message=$1 WHERE id=$2",
                        str(e)[:500],
                        upload_id,
                    )
            except Exception:
                pass
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug("temp_file_removed", path=temp_path)
            except Exception as cleanup_err:
                logger.warning("temp_file_remove_failed", path=temp_path, error=str(cleanup_err))


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("")
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    context: SecurityContext = Depends(get_security_context),
):
    """
    Accept an Excel file upload, stream it to disk (max 25 MB),
    and fire a background task to convert it to Parquet.
    Returns 202 immediately with the upload_id for status polling.
    """
    user_id = context.user_id
    session_id = request.headers.get("X-Session-Id")

    # ── Validate file extension ──────────────────────────────────────────────
    fname = file.filename or ""
    if not fname.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx or .xls files are supported.",
        )

    # ── Early size check via Content-Length header ───────────────────────────
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 25 MB limit.")

    upload_id = str(uuid.uuid4())
    temp_path = os.path.join(UPLOAD_DIR, f"temp_{upload_id}_{fname}")

    # ── Stream to disk with byte-level guard ─────────────────────────────────
    total_bytes = 0
    try:
        with open(temp_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE:
                    f.close()
                    os.remove(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 25 MB limit.",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("file_save_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save file.")

    # ── Insert placeholder row (status=processing) ───────────────────────────
    db_manager: DatabaseManager = request.app.state.db_manager
    pool = db_manager.get_pool("postgres")
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO document_uploads
                        (id, user_id, session_id, filename, parquet_path,
                         row_count, schema_json, sheet_names, status, expires_at)
                    VALUES ($1,$2,$3,$4,$5,0,'{}','[]','processing', CURRENT_TIMESTAMP + INTERVAL '24 hours')
                    """,
                    upload_id,
                    user_id,
                    session_id,
                    fname,
                    temp_path,  # placeholder; updated by background task
                )
        except Exception as e:
            logger.error("upload_insert_failed", error=str(e))
            # Don't block — background task will still run

    # ── Fire background conversion (keep reference to prevent GC drop) ───────
    task = asyncio.create_task(
        process_excel_to_parquet(
            temp_path=temp_path,
            original_filename=fname,
            upload_id=upload_id,
            user_id=user_id,
            session_id=session_id,
            db_manager=db_manager,
        )
    )
    # Store on app state so the task survives until completion
    pending: set = getattr(request.app.state, "bg_upload_tasks", set())
    pending.add(task)
    task.add_done_callback(pending.discard)
    request.app.state.bg_upload_tasks = pending

    return JSONResponse(
        status_code=202,
        content={
            "status": "processing",
            "upload_id": upload_id,
            "filename": fname,
            "message": "File received. Converting — poll /status for readiness.",
        },
    )


@router.get("/{upload_id}/status")
async def get_upload_status(
    upload_id: str,
    request: Request,
    context: SecurityContext = Depends(get_security_context),
):
    """
    Poll this endpoint after uploading.
    Returns: status (processing|ready|error), and full metadata when ready.
    """
    user_id = context.user_id
    db_manager: DatabaseManager = request.app.state.db_manager
    pool = db_manager.get_pool("postgres")
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, filename, status, error_message,
                       row_count, schema_json, sheet_names, created_at
                FROM document_uploads
                WHERE id=$1
                """,
                upload_id,
            )
    except Exception as e:
        logger.error("get_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch status.")

    if not row:
        raise HTTPException(status_code=404, detail="Upload not found.")

    result: dict[str, Any] = {
        "upload_id": str(row["id"]),
        "filename": row["filename"],
        "status": row["status"],
    }

    if row["status"] == "ready":
        try:
            schema = json.loads(row["schema_json"]) if isinstance(row["schema_json"], str) else (row["schema_json"] or {})
            sheets = json.loads(row["sheet_names"]) if isinstance(row["sheet_names"], str) else (row["sheet_names"] or [])
        except Exception:
            schema, sheets = {}, []

        result.update({
            "row_count": row["row_count"],
            "schema": schema,
            "sheet_names": sheets,
            "created_at": row["created_at"].isoformat() + "Z" if row["created_at"] else None,
        })
    elif row["status"] == "error":
        result["error"] = row["error_message"] or "Conversion failed."

    return result


@router.get("")
async def get_user_uploads(
    request: Request,
    context: SecurityContext = Depends(get_security_context),
):
    """
    List all ready uploads for the current user in the current session.
    Pass X-Session-Id header to scope results to that session.
    """
    user_id = context.user_id
    session_id = request.headers.get("X-Session-Id")
    db_manager: DatabaseManager = request.app.state.db_manager
    pool = db_manager.get_pool("postgres")
    if not pool:
        return {"uploads": []}

    try:
        async with pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    """
                    SELECT id, filename, row_count, schema_json, sheet_names,
                           created_at, status
                    FROM document_uploads
                    WHERE LOWER(user_id)=LOWER($1) AND session_id=$2 AND status='ready'
                    ORDER BY created_at DESC
                    """,
                    user_id,
                    session_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, filename, row_count, schema_json, sheet_names,
                           created_at, status
                    FROM document_uploads
                    WHERE LOWER(user_id)=LOWER($1) AND status='ready'
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    user_id,
                )

        uploads = []
        for r in rows:
            try:
                schema = json.loads(r["schema_json"]) if isinstance(r["schema_json"], str) else (r["schema_json"] or {})
                sheets = json.loads(r["sheet_names"]) if isinstance(r["sheet_names"], str) else (r["sheet_names"] or [])
            except Exception:
                schema, sheets = {}, []
            uploads.append({
                "id": str(r["id"]),
                "filename": r["filename"],
                "row_count": r["row_count"],
                "schema": schema,
                "sheet_names": sheets,
                "created_at": r["created_at"].isoformat() + "Z" if r["created_at"] else None,
            })
        return {"uploads": uploads}

    except Exception as e:
        logger.error("get_uploads_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch uploads.")


@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: str,
    request: Request,
    context: SecurityContext = Depends(get_security_context),
):
    """Delete a single upload (ownership verified). Removes DB row + Parquet file."""
    user_id = context.user_id
    db_manager: DatabaseManager = request.app.state.db_manager
    pool = db_manager.get_pool("postgres")
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT parquet_path FROM document_uploads WHERE id=$1 AND user_id=$2",
                upload_id,
                user_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Upload not found.")

            await conn.execute(
                "DELETE FROM document_uploads WHERE id=$1", upload_id
            )

        parquet_path = row["parquet_path"]
        if parquet_path and os.path.exists(parquet_path):
            try:
                os.remove(parquet_path)
                logger.info("upload_deleted", upload_id=upload_id, path=parquet_path)
            except Exception as e:
                logger.warning("parquet_delete_failed", path=parquet_path, error=str(e))

        return {"deleted": True, "upload_id": upload_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_upload_failed", upload_id=upload_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to delete upload.")


@router.delete("/by-session/{session_id}")
async def delete_session_uploads(session_id: str, request: Request):
    """
    Bulk-delete all uploads for a session.
    Called by the C# layer when a chat session is deleted.
    Auth: any authenticated user (C# already verified ownership of the session).
    """
    db_manager: DatabaseManager = request.app.state.db_manager
    pool = db_manager.get_pool("postgres")
    if not pool:
        return {"deleted": 0}

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, parquet_path FROM document_uploads WHERE session_id=$1",
                session_id,
            )
            if not rows:
                return {"deleted": 0}

            upload_ids = [str(r["id"]) for r in rows]
            await conn.execute(
                "DELETE FROM document_uploads WHERE session_id=$1", session_id
            )

        deleted_files = 0
        for r in rows:
            path = r["parquet_path"]
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    deleted_files += 1
                except Exception as e:
                    logger.warning("bulk_parquet_delete_failed", path=path, error=str(e))

        logger.info(
            "session_uploads_deleted",
            session_id=session_id,
            db_rows=len(upload_ids),
            files_removed=deleted_files,
        )
        return {"deleted": len(upload_ids), "files_removed": deleted_files}

    except Exception as e:
        logger.error("delete_session_uploads_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to delete session uploads.")

# ─── Cleanup Job ─────────────────────────────────────────────────────────────

async def _cleanup_expired_uploads(db_manager: DatabaseManager):
    """
    Periodically queries the database for expired uploads and deletes them
    from disk and the database.
    """
    while True:
        try:
            pool = db_manager.get_pool("postgres")
            if pool:
                async with pool.acquire() as conn:
                    # Find expired records
                    rows = await conn.fetch(
                        "SELECT id, parquet_path FROM document_uploads WHERE expires_at < CURRENT_TIMESTAMP"
                    )
                    
                    if rows:
                        for row in rows:
                            upload_id = str(row["id"])
                            path = row["parquet_path"]
                            
                            # Attempt to delete the file
                            if path and os.path.exists(path):
                                try:
                                    os.remove(path)
                                    logger.info("expired_file_deleted", upload_id=upload_id, path=path)
                                except Exception as e:
                                    logger.warning("expired_file_delete_failed", upload_id=upload_id, error=str(e))
                        
                        # Remove from DB
                        expired_ids = [row["id"] for row in rows]
                        await conn.execute(
                            "DELETE FROM document_uploads WHERE id = ANY($1)",
                            expired_ids
                        )
                        logger.info("expired_db_records_deleted", count=len(expired_ids))
        except asyncio.CancelledError:
            logger.info("cleanup_job_cancelled")
            break
        except Exception as e:
            logger.error("cleanup_job_error", error=str(e))
        
        # Run every 1 hour
        await asyncio.sleep(3600)

_cleanup_task = None

def start_cleanup_job(db_manager: DatabaseManager):
    """Starts the background cleanup job."""
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = asyncio.create_task(_cleanup_expired_uploads(db_manager))
        logger.info("cleanup_job_started")

def stop_cleanup_job():
    """Stops the background cleanup job."""
    global _cleanup_task
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        _cleanup_task = None
        logger.info("cleanup_job_stopped")
