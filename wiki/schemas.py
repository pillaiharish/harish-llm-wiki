"""Pydantic schemas for Harish LLM Wiki."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class SourceType(str, Enum):
    """Type of resource source."""

    YOUTUBE = "youtube"
    WEBPAGE = "webpage"
    MARKDOWN = "markdown"
    MEDIUM_MARKDOWN = "medium_markdown"


class ResourceStatus(str, Enum):
    """Status of a resource in the pipeline."""

    NEW = "new"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    RAW_SAVED = "raw_saved"
    NORMALIZED = "normalized"
    LLM_NOTE_GENERATED = "llm_note_generated"
    LLM_CACHE_HIT = "llm_cache_hit"
    SITE_GENERATED = "site_generated"
    PROCESSED = "processed"
    NEEDS_MANUAL_MARKDOWN = "needs_manual_markdown"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class Importance(str, Enum):
    """Importance level of a resource."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# =============================================================================
# Resource Identity
# =============================================================================

class ResourceIdentity(BaseModel):
    """Canonical identity for a resource."""

    source_type: SourceType
    canonical_id: str
    original_url: str
    normalized_url: Optional[str] = None
    content_hash: Optional[str] = None

    # YouTube-specific
    video_id: Optional[str] = None
    start_time_seconds: Optional[int] = None
    important_timestamps: List[int] = Field(default_factory=list)

    # Webpage-specific
    domain: Optional[str] = None


# =============================================================================
# Resource Record (Registry)
# =============================================================================

class ResourceRecord(BaseModel):
    """Complete record of a resource in the registry."""

    # Identity
    id: str = Field(..., description="Canonical resource ID")
    source_type: SourceType
    canonical_id: str

    # URLs
    original_url: str
    normalized_url: Optional[str] = None

    # Content identification
    content_hash: Optional[str] = None

    # Metadata
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    description: Optional[str] = None

    # User metadata
    user_added_at: Optional[datetime] = None
    user_consumed_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    importance: Importance = Importance.MEDIUM
    notes_from_user: Optional[str] = None

    # Status tracking
    status: ResourceStatus = ResourceStatus.NEW
    failure_reason: Optional[str] = None

    # Timestamps
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # File paths
    local_raw_path: Optional[Path] = None
    local_normalized_path: Optional[Path] = None
    generated_note_path: Optional[Path] = None

    # LLM tracking
    prompt_hash: Optional[str] = None
    source_chunks_hash: Optional[str] = None
    generated_output_hash: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    prompt_version: Optional[str] = None

    # Extra metadata
    extra: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Source Chunks
# =============================================================================

class SourceChunk(BaseModel):
    """Base class for citeable source chunks."""

    resource_id: str
    chunk_id: str
    source_type: SourceType
    text: str
    citation_label: str


class YouTubeChunk(SourceChunk):
    """A citeable chunk from a YouTube transcript."""

    source_type: SourceType = SourceType.YOUTUBE
    start_time: float
    end_time: float
    url: Optional[str] = None

    @property
    def citation_label_formatted(self) -> str:
        """Format as timestamp range."""
        start = self._format_timestamp(self.start_time)
        end = self._format_timestamp(self.end_time)
        return f"{start}-{end}"

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Convert seconds to HH:MM:SS format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


class WebpageChunk(SourceChunk):
    """A citeable chunk from a webpage."""

    source_type: SourceType = SourceType.WEBPAGE
    section_heading: Optional[str] = None
    paragraph_index: Optional[int] = None
    url: Optional[str] = None

    @property
    def citation_label_formatted(self) -> str:
        """Format as section/paragraph reference."""
        if self.section_heading and self.paragraph_index is not None:
            return f'{self.section_heading}, paragraph {self.paragraph_index}'
        elif self.section_heading:
            return self.section_heading
        elif self.paragraph_index is not None:
            return f"paragraph {self.paragraph_index}"
        return self.citation_label


class MarkdownChunk(SourceChunk):
    """A citeable chunk from a Markdown file."""

    source_type: SourceType = SourceType.MARKDOWN
    section_heading: Optional[str] = None
    paragraph_index: Optional[int] = None
    file_path: Optional[str] = None

    @property
    def citation_label_formatted(self) -> str:
        """Format as section/paragraph reference."""
        if self.section_heading and self.paragraph_index is not None:
            return f'{self.section_heading}, paragraph {self.paragraph_index}'
        elif self.section_heading:
            return self.section_heading
        elif self.paragraph_index is not None:
            return f"paragraph {self.paragraph_index}"
        return self.citation_label


# Union type for all chunks
ChunkType = YouTubeChunk | WebpageChunk | MarkdownChunk


# =============================================================================
# Generated Notes
# =============================================================================

class Citation(BaseModel):
    """A citation linking a claim to source chunks."""

    claim: str
    source_chunk_ids: List[str]
    citation_label: str


class GeneratedNote(BaseModel):
    """An LLM-generated learning note for a resource."""

    # Identity
    resource_id: str

    # LLM metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    llm_provider: str
    llm_model: str
    prompt_version: str

    # Content
    title: str
    summary: str
    concepts: List[str] = Field(default_factory=list)

    # Karpathy-style note sections
    why_matters: str
    memory_hook: str
    coverage: List[str] = Field(default_factory=list)
    karpathy_explanation: str
    source_backed_notes: str
    timeline_of_ideas: str
    examples: str
    missing_pieces: List[str] = Field(default_factory=list)
    llm_added_explanations: str
    related_concepts: List[str] = Field(default_factory=list)
    revision_questions: List[str] = Field(default_factory=list)
    project_connections: str

    # Citations and provenance
    citations: List[Citation] = Field(default_factory=list)
    requires_human_review: bool = False

    # Source hashes for caching
    source_chunks_hash: str
    prompt_hash: str


# =============================================================================
# Concept
# =============================================================================

class ConceptResourceRef(BaseModel):
    """Reference to a resource that discusses this concept."""

    resource_id: str
    resource_title: str
    coverage_quality: str  # "full", "partial", "brief"
    learned_at: datetime


class Concept(BaseModel):
    """A concept extracted from resources."""

    name: str
    slug: str
    definition: str
    mental_model: str
    why_relevant: str
    resources: List[ConceptResourceRef] = Field(default_factory=list)
    best_explanation_resource_id: Optional[str] = None
    confusing_parts: List[str] = Field(default_factory=list)
    llm_added_clarification: str
    practical_implementation: str
    related_concept_slugs: List[str] = Field(default_factory=list)
    revision_questions: List[str] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


# =============================================================================
# Timeline
# =============================================================================

class TimelineEntry(BaseModel):
    """An entry in the learning timeline."""

    date: datetime
    period_label: str  # e.g., "September 2025"
    resource_id: str
    resource_title: str
    resource_type: SourceType
    concepts_learned: List[str] = Field(default_factory=list)
    summary: str


class TimelinePeriod(BaseModel):
    """A time period grouping timeline entries."""

    period_label: str
    theme: Optional[str] = None
    entries: List[TimelineEntry] = Field(default_factory=list)
    concepts_learned: List[str] = Field(default_factory=list)


# =============================================================================
# Gaps
# =============================================================================

class KnowledgeGap(BaseModel):
    """A identified gap in knowledge."""

    concept_name: str
    gap_type: str  # "needs_verification", "weak_examples", "no_project_connection",
    # "missing_explanation", "needs_human_review"
    mentioned_in: List[str] = Field(default_factory=list)
    problem_description: str
    suggested_action: str


class GapsReport(BaseModel):
    """Report of all knowledge gaps."""

    needs_verification: List[KnowledgeGap] = Field(default_factory=list)
    weak_examples: List[KnowledgeGap] = Field(default_factory=list)
    missing_project_connection: List[KnowledgeGap] = Field(default_factory=list)
    needs_human_review: List[KnowledgeGap] = Field(default_factory=list)
    resources_missing_metadata: List[str] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Batch Processing
# =============================================================================

class BatchAddResult(BaseModel):
    """Result of adding a batch of resources."""

    total_lines: int
    valid_urls: int
    new_resources: int
    duplicates_skipped: int
    unsupported_urls: int
    errors: List[str] = Field(default_factory=list)


# =============================================================================
# Validation
# =============================================================================

class ValidationIssue(BaseModel):
    """A single validation issue."""

    severity: str  # "error", "warning", "info"
    issue_type: str
    resource_id: Optional[str] = None
    message: str
    suggestion: Optional[str] = None


class ValidationReport(BaseModel):
    """Complete validation report."""

    issues: List[ValidationIssue] = Field(default_factory=list)
    total_resources: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    passed: bool = False

    generated_at: datetime = Field(default_factory=datetime.utcnow)
