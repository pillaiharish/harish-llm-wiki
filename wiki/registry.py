"""Resource registry using SQLite and JSONL logs."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Iterator

from wiki.config import config
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType
from wiki.dedupe import ResourceIdentity


class Registry:
    """SQLite-based resource registry with JSONL logging."""
    
    def __init__(self) -> None:
        """Initialize the registry."""
        self.db_path = config.get_data_path("registry", "resources.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize the SQLite database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    canonical_id TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    normalized_url TEXT,
                    content_hash TEXT,
                    title TEXT,
                    author TEXT,
                    published_at TEXT,
                    description TEXT,
                    user_added_at TEXT,
                    user_consumed_at TEXT,
                    tags TEXT,  -- JSON array
                    importance TEXT DEFAULT 'medium',
                    notes_from_user TEXT,
                    status TEXT DEFAULT 'new',
                    failure_reason TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    processed_at TEXT,
                    updated_at TEXT,
                    local_raw_path TEXT,
                    local_normalized_path TEXT,
                    generated_note_path TEXT,
                    prompt_hash TEXT,
                    source_chunks_hash TEXT,
                    generated_output_hash TEXT,
                    llm_provider TEXT,
                    llm_model TEXT,
                    prompt_version TEXT,
                    extra TEXT  -- JSON object
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON resources(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_type ON resources(source_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_canonical_id ON resources(canonical_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_last_seen ON resources(last_seen_at)")
    
    def _row_to_record(self, row: sqlite3.Row) -> ResourceRecord:
        """Convert a database row to a ResourceRecord."""
        return ResourceRecord(
            id=row['id'],
            source_type=SourceType(row['source_type']),
            canonical_id=row['canonical_id'],
            original_url=row['original_url'],
            normalized_url=row['normalized_url'],
            content_hash=row['content_hash'],
            title=row['title'],
            author=row['author'],
            published_at=datetime.fromisoformat(row['published_at']) if row['published_at'] else None,
            description=row['description'],
            user_added_at=datetime.fromisoformat(row['user_added_at']) if row['user_added_at'] else None,
            user_consumed_at=datetime.fromisoformat(row['user_consumed_at']) if row['user_consumed_at'] else None,
            tags=json.loads(row['tags']) if row['tags'] else [],
            importance=row['importance'],
            notes_from_user=row['notes_from_user'],
            status=ResourceStatus(row['status']),
            failure_reason=row['failure_reason'],
            first_seen_at=datetime.fromisoformat(row['first_seen_at']),
            last_seen_at=datetime.fromisoformat(row['last_seen_at']),
            processed_at=datetime.fromisoformat(row['processed_at']) if row['processed_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
            local_raw_path=Path(row['local_raw_path']) if row['local_raw_path'] else None,
            local_normalized_path=Path(row['local_normalized_path']) if row['local_normalized_path'] else None,
            generated_note_path=Path(row['generated_note_path']) if row['generated_note_path'] else None,
            prompt_hash=row['prompt_hash'],
            source_chunks_hash=row['source_chunks_hash'],
            generated_output_hash=row['generated_output_hash'],
            llm_provider=row['llm_provider'],
            llm_model=row['llm_model'],
            prompt_version=row['prompt_version'],
            extra=json.loads(row['extra']) if row['extra'] else {}
        )
    
    def _record_to_row(self, record: ResourceRecord) -> dict:
        """Convert a ResourceRecord to a database row dict."""
        return {
            'id': record.id,
            'source_type': record.source_type.value,
            'canonical_id': record.canonical_id,
            'original_url': record.original_url,
            'normalized_url': record.normalized_url,
            'content_hash': record.content_hash,
            'title': record.title,
            'author': record.author,
            'published_at': record.published_at.isoformat() if record.published_at else None,
            'description': record.description,
            'user_added_at': record.user_added_at.isoformat() if record.user_added_at else None,
            'user_consumed_at': record.user_consumed_at.isoformat() if record.user_consumed_at else None,
            'tags': json.dumps(record.tags) if record.tags else '[]',
            'importance': record.importance,
            'notes_from_user': record.notes_from_user,
            'status': record.status.value,
            'failure_reason': record.failure_reason,
            'first_seen_at': record.first_seen_at.isoformat(),
            'last_seen_at': record.last_seen_at.isoformat(),
            'processed_at': record.processed_at.isoformat() if record.processed_at else None,
            'updated_at': record.updated_at.isoformat() if record.updated_at else None,
            'local_raw_path': str(record.local_raw_path) if record.local_raw_path else None,
            'local_normalized_path': str(record.local_normalized_path) if record.local_normalized_path else None,
            'generated_note_path': str(record.generated_note_path) if record.generated_note_path else None,
            'prompt_hash': record.prompt_hash,
            'source_chunks_hash': record.source_chunks_hash,
            'generated_output_hash': record.generated_output_hash,
            'llm_provider': record.llm_provider,
            'llm_model': record.llm_model,
            'prompt_version': record.prompt_version,
            'extra': json.dumps(record.extra) if record.extra else '{}'
        }
    
    def get_by_canonical_id(self, canonical_id: str) -> Optional[ResourceRecord]:
        """Get a resource by its canonical ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM resources WHERE canonical_id = ?",
                (canonical_id,)
            ).fetchone()
            if row:
                return self._row_to_record(row)
            return None
    
    def get_by_id(self, resource_id: str) -> Optional[ResourceRecord]:
        """Get a resource by its ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM resources WHERE id = ?",
                (resource_id,)
            ).fetchone()
            if row:
                return self._row_to_record(row)
            return None
    
    def insert(self, identity: ResourceIdentity, status: ResourceStatus = ResourceStatus.NEW) -> ResourceRecord:
        """Insert a new resource into the registry."""
        now = datetime.utcnow()
        
        record = ResourceRecord(
            id=identity.canonical_id,
            source_type=identity.source_type,
            canonical_id=identity.canonical_id,
            original_url=identity.original_url,
            normalized_url=identity.normalized_url,
            content_hash=identity.content_hash,
            status=status,
            first_seen_at=now,
            last_seen_at=now,
            extra={
                'video_id': identity.video_id,
                'start_time_seconds': identity.start_time_seconds,
                'important_timestamps': identity.important_timestamps,
                'domain': identity.domain
            }
        )
        
        row = self._record_to_row(record)
        
        with sqlite3.connect(self.db_path) as conn:
            columns = ', '.join(row.keys())
            placeholders = ', '.join(['?' for _ in row])
            conn.execute(
                f"INSERT INTO resources ({columns}) VALUES ({placeholders})",
                tuple(row.values())
            )
        
        # Append to JSONL log
        self._append_to_jsonl_log(record)
        
        return record
    
    def update(self, record: ResourceRecord) -> None:
        """Update an existing resource."""
        record.updated_at = datetime.utcnow()
        row = self._record_to_row(record)
        
        with sqlite3.connect(self.db_path) as conn:
            set_clause = ', '.join([f"{k} = ?" for k in row.keys() if k != 'id'])
            values = tuple(v for k, v in row.items() if k != 'id') + (row['id'],)
            conn.execute(
                f"UPDATE resources SET {set_clause} WHERE id = ?",
                values
            )
    
    def update_status(self, resource_id: str, status: ResourceStatus, 
                     failure_reason: Optional[str] = None) -> None:
        """Update just the status of a resource."""
        now = datetime.utcnow()
        with sqlite3.connect(self.db_path) as conn:
            if failure_reason:
                conn.execute(
                    "UPDATE resources SET status = ?, failure_reason = ?, updated_at = ? WHERE id = ?",
                    (status.value, failure_reason, now.isoformat(), resource_id)
                )
            else:
                conn.execute(
                    "UPDATE resources SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, now.isoformat(), resource_id)
                )
    
    def update_timestamps(self, resource_id: str, new_timestamp: int) -> None:
        """Update important timestamps for a resource (for YouTube)."""
        record = self.get_by_id(resource_id)
        if record and new_timestamp:
            existing = record.extra.get('important_timestamps', [])
            if new_timestamp not in existing:
                existing.append(new_timestamp)
                existing.sort()
                record.extra['important_timestamps'] = existing
                record.last_seen_at = datetime.utcnow()
                self.update(record)
    
    def get_all(self, status: Optional[ResourceStatus] = None) -> Iterator[ResourceRecord]:
        """Get all resources, optionally filtered by status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM resources WHERE status = ? ORDER BY first_seen_at DESC",
                    (status.value,)
                )
            else:
                rows = conn.execute("SELECT * FROM resources ORDER BY first_seen_at DESC")
            
            for row in rows:
                yield self._row_to_record(row)
    
    def get_pending(self) -> Iterator[ResourceRecord]:
        """Get resources that need processing (status=new or failed_retryable)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM resources 
                   WHERE status IN ('new', 'failed_retryable') 
                   ORDER BY first_seen_at DESC"""
            )
            for row in rows:
                yield self._row_to_record(row)
    
    def count_by_status(self) -> dict:
        """Get counts of resources by status."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM resources GROUP BY status"
            )
            return {row[0]: row[1] for row in rows}
    
    def _append_to_jsonl_log(self, record: ResourceRecord) -> None:
        """Append record to JSONL log for audit trail."""
        log_path = config.get_data_path("registry", "resources.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": "insert",
            "resource_id": record.id,
            "canonical_id": record.canonical_id,
            "source_type": record.source_type.value,
            "status": record.status.value
        }
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")


# Global registry instance
registry = Registry()
