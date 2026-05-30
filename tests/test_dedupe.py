"""Tests for deduplication logic."""

import pytest

from wiki.dedupe import deduplicator, extract_youtube_video_id, normalize_url


class TestYouTubeExtraction:
    """Test YouTube URL extraction."""
    
    def test_standard_url(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI"
        assert extract_youtube_video_id(url) == "r2m9DbEmeqI"
    
    def test_short_url(self):
        url = "https://youtu.be/r2m9DbEmeqI"
        assert extract_youtube_video_id(url) == "r2m9DbEmeqI"
    
    def test_url_with_timestamp(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI&t=670s"
        assert extract_youtube_video_id(url) == "r2m9DbEmeqI"
    
    def test_url_with_params(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI&list=playlist"
        assert extract_youtube_video_id(url) == "r2m9DbEmeqI"
    
    def test_invalid_url(self):
        url = "https://example.com"
        assert extract_youtube_video_id(url) is None


class TestURLNormalization:
    """Test URL normalization."""
    
    def test_lowercase_domain(self):
        url = "https://EXAMPLE.COM/path"
        assert "example.com" in normalize_url(url)
    
    def test_remove_www(self):
        url = "https://www.example.com/path"
        assert "www." not in normalize_url(url)
    
    def test_remove_tracking_params(self):
        url = "https://example.com/path?utm_source=google"
        normalized = normalize_url(url)
        assert "utm_source" not in normalized
    
    def test_preserve_important_params(self):
        url = "https://example.com/watch?v=abc123"
        normalized = normalize_url(url)
        assert "v=abc123" in normalized


class TestCanonicalization:
    """Test resource canonicalization."""
    
    def test_youtube_canonicalization(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI&t=670s"
        identity = deduplicator.canonicalize_youtube(url)
        
        assert identity is not None
        assert identity.canonical_id == "youtube:r2m9DbEmeqI"
        assert identity.video_id == "r2m9DbEmeqI"
        assert identity.start_time_seconds == 670
    
    def test_youtube_canonicalization_no_timestamp(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI"
        identity = deduplicator.canonicalize_youtube(url)
        
        assert identity is not None
        assert identity.canonical_id == "youtube:r2m9DbEmeqI"
        assert identity.start_time_seconds is None
    
    def test_webpage_canonicalization(self):
        url = "https://www.example.com/article?utm_source=google"
        identity = deduplicator.canonicalize_webpage(url)
        
        assert identity is not None
        assert identity.canonical_id.startswith("webpage:")
        assert identity.domain == "example.com"
        assert "utm_source" not in (identity.normalized_url or "")


class TestDuplicateDetection:
    """Test duplicate detection."""
    
    def test_youtube_same_video_different_urls(self):
        urls = [
            "https://www.youtube.com/watch?v=r2m9DbEmeqI",
            "https://youtube.com/watch?v=r2m9DbEmeqI",
            "https://youtu.be/r2m9DbEmeqI",
        ]
        
        ids = []
        for url in urls:
            identity = deduplicator.canonicalize(url)
            if identity:
                ids.append(identity.canonical_id)
        
        # All should have the same canonical ID
        assert len(set(ids)) == 1
    
    def test_youtube_different_videos(self):
        urls = [
            "https://www.youtube.com/watch?v=r2m9DbEmeqI",
            "https://www.youtube.com/watch?v=abcdef12345",
        ]
        
        ids = []
        for url in urls:
            identity = deduplicator.canonicalize(url)
            if identity:
                ids.append(identity.canonical_id)
        
        # Should have different canonical IDs
        assert len(set(ids)) == 2


class TestTimestampHandling:
    """Test timestamp extraction and merging."""
    
    def test_extract_timestamp_seconds(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI&t=670s"
        identity = deduplicator.canonicalize_youtube(url)
        assert identity.start_time_seconds == 670
    
    def test_extract_timestamp_no_unit(self):
        url = "https://www.youtube.com/watch?v=r2m9DbEmeqI&t=670"
        identity = deduplicator.canonicalize_youtube(url)
        assert identity.start_time_seconds == 670
    
    def test_merge_timestamps(self):
        existing = [100, 200]
        new = 150
        result = deduplicator.merge_timestamps(existing, new)
        assert result == [100, 150, 200]
    
    def test_merge_timestamps_duplicate(self):
        existing = [100, 200]
        new = 100
        result = deduplicator.merge_timestamps(existing, new)
        assert result == [100, 200]
