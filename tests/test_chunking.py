"""Tests for chunking logic."""

import pytest

from wiki.normalize.chunker import chunker
from wiki.schemas import SourceType, YouTubeChunk, WebpageChunk, MarkdownChunk


class TestYouTubeChunking:
    """Test YouTube transcript chunking."""
    
    def test_chunk_youtube_transcript(self):
        entries = [
            {"text": "Hello world", "start": 0.0, "duration": 5.0},
            {"text": "This is a test", "start": 5.0, "duration": 5.0},
            {"text": "More content here", "start": 10.0, "duration": 5.0},
        ]
        
        chunks = list(chunker.chunk_youtube_transcript(
            entries, "video123", "youtube:video123"
        ))
        
        assert len(chunks) > 0
        assert all(isinstance(c, YouTubeChunk) for c in chunks)
        assert chunks[0].resource_id == "youtube:video123"
    
    def test_chunk_preserves_timestamps(self):
        entries = [
            {"text": "Start", "start": 0.0, "duration": 5.0},
            {"text": "End", "start": 5.0, "duration": 5.0},
        ]
        
        chunks = list(chunker.chunk_youtube_transcript(
            entries, "video123", "youtube:video123"
        ))
        
        assert chunks[0].start_time == 0.0
        assert chunks[0].end_time == 10.0


class TestTextChunking:
    """Test text (webpage/markdown) chunking."""
    
    def test_chunk_webpage(self):
        text = """
# Introduction

This is a paragraph about something important. It has enough content to be meaningful.

## Section 1

More content here. Even more text to make sure we have sufficient length for a chunk.
"""
        
        chunks = list(chunker.chunk_text(
            text, "webpage:abc123", SourceType.WEBPAGE, url="https://example.com"
        ))
        
        assert len(chunks) > 0
        assert all(isinstance(c, WebpageChunk) for c in chunks)
    
    def test_chunk_preserves_sections(self):
        text = """# Title

Content under title.

## Section 1

Content under section 1.

## Section 2

Content under section 2.
"""
        
        chunks = list(chunker.chunk_text(
            text, "webpage:abc123", SourceType.WEBPAGE
        ))
        
        # At least one chunk should have section heading
        sections = [c.section_heading for c in chunks if c.section_heading]
        assert len(sections) > 0


class TestSectionSplitting:
    """Test section splitting logic."""
    
    def test_split_by_headers(self):
        text = """# Header 1
Content 1

## Header 2
Content 2

# Header 3
Content 3
"""
        
        sections = chunker._split_into_sections(text)
        
        assert len(sections) == 3
        assert sections[0][0] == "Header 1"
        assert sections[1][0] == "Header 2"
        assert sections[2][0] == "Header 3"
    
    def test_no_headers(self):
        text = "Just some content without headers."
        
        sections = chunker._split_into_sections(text)
        
        assert len(sections) == 1
        assert sections[0][0] is None
