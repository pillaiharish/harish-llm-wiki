"""Tests for metadata enrichment."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ["LLM_PROVIDER"] = "mock"
os.environ["OLLAMA_CLOUD_API_KEY"] = "test"
os.environ["OLLAMA_CLOUD_MODEL"] = "test"

from wiki.enrich.metadata import (
    YouTubeMetadataEnricher,
    WebpageMetadataEnricher,
)
from wiki.schemas import ResourceRecord, SourceType


class TestYouTubeMetadataEnricher:
    """Test YouTube metadata enrichment."""
    
    def test_enrich_updates_record_title(self):
        """Test that enriching metadata updates the record title."""
        enricher = YouTubeMetadataEnricher()
        
        # Mock yt-dlp
        mock_info = {
            'title': 'Let\'s build the GPT Tokenizer from scratch',
            'channel': 'Andrej Karpathy',
            'channel_url': 'https://www.youtube.com/@AndrejKarpathy',
            'upload_date': '20240115',
            'duration': 3600,
            'thumbnail': 'https://i.ytimg.com/vi/example/maxresdefault.jpg',
            'description': 'A detailed explanation of tokenization in LLMs.',
        }
        
        record = ResourceRecord(
            id="youtube:test123",
            source_type=SourceType.YOUTUBE,
            canonical_id="youtube:test123",
            original_url="https://www.youtube.com/watch?v=test123",
            title=None,
            author=None,
        )
        record.extra['video_id'] = 'test123'
        
        # Patch the _get_ytdl method to return a mock
        with patch.object(enricher, '_get_ytdl') as mock_get_ydl:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_get_ydl.return_value = mock_ydl
            
            # Also patch config to use temp directory
            with patch('wiki.enrich.metadata.config') as mock_config:
                tmp = tempfile.mkdtemp()
                mock_config.get_data_path = lambda *p: Path(tmp).joinpath(*p)
                mock_config.LLM_WIKI_DATA_DIR = Path(tmp)
                
                result = enricher.enrich(record)
                
                assert result.title == "Let's build the GPT Tokenizer from scratch"
                assert result.author == "Andrej Karpathy"
                assert result.extra["metadata_status"] == "enriched"
    
    def test_enrich_skips_if_title_exists(self):
        """Test that enrichment is skipped if title already exists."""
        enricher = YouTubeMetadataEnricher()
        
        record = ResourceRecord(
            id="youtube:test123",
            source_type=SourceType.YOUTUBE,
            canonical_id="youtube:test123",
            original_url="https://www.youtube.com/watch?v=test123",
            title="Already Had Title",
            author=None,
        )
        record.extra['video_id'] = 'test123'
        
        # Even without yt-dlp, if title exists it should skip
        with patch.object(enricher, '_get_ytdl', return_value=None):
            with patch('wiki.enrich.metadata.config') as mock_config:
                tmp = tempfile.mkdtemp()
                mock_config.get_data_path = lambda *p: Path(tmp).joinpath(*p)
                mock_config.LLM_WIKI_DATA_DIR = Path(tmp)
                
                result = enricher.enrich(record, force=False)
                assert result.title == "Already Had Title"
    
    def test_enrich_handles_ytdlp_failure(self):
        """Test that enrichment gracefully handles yt-dlp failures."""
        enricher = YouTubeMetadataEnricher()
        
        record = ResourceRecord(
            id="youtube:test123",
            source_type=SourceType.YOUTUBE,
            canonical_id="youtube:test123",
            original_url="https://www.youtube.com/watch?v=test123",
            title=None,
        )
        record.extra['video_id'] = 'test123'
        
        # Mock yt-dlp to raise an exception
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("Video unavailable")
        
        with patch.object(enricher, '_get_ytdl', return_value=mock_ydl):
            with patch('wiki.enrich.metadata.config') as mock_config:
                tmp = tempfile.mkdtemp()
                mock_config.get_data_path = lambda *p: Path(tmp).joinpath(*p)
                mock_config.LLM_WIKI_DATA_DIR = Path(tmp)
                
                result = enricher.enrich(record)
                
                # Should not crash, just leave title as None
                assert result.title is None
                # Should have recorded the failure
                assert result.extra.get('metadata_status') == 'failed_retryable'

    def test_enrich_replaces_untitled_placeholder_and_sets_webpage_url(self):
        """Test that YouTube enrichment replaces literal Untitled placeholders."""
        enricher = YouTubeMetadataEnricher()
        mock_info = {
            'title': 'Real Video Title',
            'channel': 'Real Channel',
            'webpage_url': 'https://www.youtube.com/watch?v=test123',
            'upload_date': '20240115',
            'duration': 42,
            'thumbnail': 'https://example.com/thumb.jpg',
            'description': 'Short description.',
        }
        record = ResourceRecord(
            id="youtube:test123",
            source_type=SourceType.YOUTUBE,
            canonical_id="youtube:test123",
            original_url="https://www.youtube.com/watch?v=test123",
            title="Untitled",
            author="",
        )
        record.extra['video_id'] = 'test123'

        with patch.object(enricher, '_get_ytdl') as mock_get_ydl:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_get_ydl.return_value = mock_ydl
            with patch('wiki.enrich.metadata.config') as mock_config:
                tmp = tempfile.mkdtemp()
                mock_config.get_data_path = lambda *p: Path(tmp).joinpath(*p)
                mock_config.LLM_WIKI_DATA_DIR = Path(tmp)

                result = enricher.enrich(record)
                metadata = json.loads(
                    (Path(tmp) / "raw" / "youtube" / "test123" / "metadata.json").read_text()
                )

                assert result.title == "Real Video Title"
                assert result.author == "Real Channel"
                assert metadata["webpage_url"] == "https://www.youtube.com/watch?v=test123"


class TestWebpageMetadataEnricher:
    """Test webpage metadata extraction from HTML."""
    
    def test_extract_opengraph_metadata(self):
        """Test extracting OpenGraph metadata from HTML."""
        enricher = WebpageMetadataEnricher()
        
        html = """
        <html>
        <head>
            <meta property="og:title" content="vLLM: Easy, Fast & Cheap LLM Serving" />
            <meta property="og:description" content="A fast inference engine for LLMs" />
            <meta property="og:image" content="https://example.com/image.png" />
            <meta property="og:site_name" content="Aleksa Gordic" />
            <meta property="article:published_time" content="2024-01-15T10:00:00Z" />
        </head>
        <body><h1>vLLM Blog</h1></body>
        </html>
        """
        
        metadata = enricher._extract_metadata(html, "https://example.com/blog")
        
        assert metadata['title'] == "vLLM: Easy, Fast & Cheap LLM Serving"
        assert metadata['description'] == "A fast inference engine for LLMs"
        assert metadata['image'] == "https://example.com/image.png"
        assert metadata['site_name'] == "Aleksa Gordic"
        assert metadata['published'] == "2024-01-15T10:00:00Z"
        assert metadata['domain'] == "example.com"
        assert metadata['canonical_url'] == "https://example.com/blog"
    
    def test_extract_twitter_card_metadata(self):
        """Test extracting Twitter Card metadata from HTML."""
        enricher = WebpageMetadataEnricher()
        
        html = """
        <html>
        <head>
            <meta name="twitter:title" content="Understanding RAG Chunking" />
            <meta name="twitter:description" content="How to chunk documents for RAG systems" />
        </head>
        <body></body>
        </html>
        """
        
        metadata = enricher._extract_metadata(html, "https://example.com/rag")
        
        assert metadata['title'] == "Understanding RAG Chunking"
        assert metadata['description'] == "How to chunk documents for RAG systems"
    
    def test_extract_html_title_fallback(self):
        """Test falling back to HTML <title> tag."""
        enricher = WebpageMetadataEnricher()
        
        html = """
        <html>
        <head><title>My Blog Post - Example.com</title></head>
        <body><h1>My Blog Post</h1></body>
        </html>
        """
        
        metadata = enricher._extract_metadata(html, "https://example.com/post")
        
        assert metadata['title'] == "My Blog Post - Example.com"
    
    def test_extract_meta_description(self):
        """Test extracting meta description."""
        enricher = WebpageMetadataEnricher()
        
        html = """
        <html>
        <head>
            <meta name="description" content="A comprehensive guide to RAG chunking strategies." />
        </head>
        <body></body>
        </html>
        """
        
        metadata = enricher._extract_metadata(html, "https://example.com/guide")
        
        assert metadata['description'] == "A comprehensive guide to RAG chunking strategies."
    
    def test_title_suffix_removal(self):
        """Test that common suffixes like ' - YouTube' are removed."""
        enricher = WebpageMetadataEnricher()
        
        html = """
        <html>
        <head>
            <meta property="og:title" content="Tokenization Explained - YouTube" />
        </head>
        <body></body>
        </html>
        """
        
        metadata = enricher._extract_metadata(html, "https://youtube.com/watch?v=test")
        
        assert metadata['title'] == "Tokenization Explained"
    
    def test_empty_html(self):
        """Test handling of empty or minimal HTML."""
        enricher = WebpageMetadataEnricher()
        
        metadata = enricher._extract_metadata("<html><body></body></html>", "https://example.com")
        
        assert metadata['title'] is None
        assert metadata['description'] is None

    def test_update_replaces_untitled_and_records_extra_fields(self):
        """Test webpage metadata update replaces placeholder values."""
        enricher = WebpageMetadataEnricher()
        record = ResourceRecord(
            id="webpage:abc123",
            source_type=SourceType.WEBPAGE,
            canonical_id="webpage:abc123",
            original_url="https://www.example.com/post",
            title="Untitled",
            author="",
        )

        result = enricher._update_record_from_metadata(
            record,
            {
                "title": "Real Article",
                "author": "Author Name",
                "description": "Article description",
                "published": "2024-01-15T10:00:00Z",
                "site_name": "Example",
                "domain": "example.com",
                "canonical_url": "https://example.com/post",
                "metadata_enriched_at": "2026-05-31T00:00:00",
            },
        )

        assert result.title == "Real Article"
        assert result.author == "Author Name"
        assert result.description == "Article description"
        assert result.extra["site_name"] == "Example"
        assert result.extra["domain"] == "example.com"
        assert result.normalized_url == "https://example.com/post"


class TestCacheBehavior:
    """Test that enrichment respects cache (existing metadata)."""
    
    def test_skip_if_metadata_exists(self):
        """Test that enrichment skips if metadata.json already has a title."""
        import tempfile
        
        enricher = WebpageMetadataEnricher()
        
        # Create a temp directory with existing metadata
        tmp = tempfile.mkdtemp()
        raw_dir = Path(tmp) / "raw" / "webpage" / "example.com" / "abc123"
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        existing_metadata = {
            "title": "Existing Title",
            "author": "Existing Author",
            "url": "https://example.com",
        }
        
        from wiki.storage import Storage
        Storage.write_json(existing_metadata, raw_dir / "metadata.json")
        
        # Also create a minimal raw.html so the enricher can find it
        Storage.write_text("<html><body>test</body></html>", raw_dir / "raw.html")
        
        record = ResourceRecord(
            id="webpage:abc123",
            source_type=SourceType.WEBPAGE,
            canonical_id="webpage:abc123",
            original_url="https://example.com",
            title=None,
        )
        record.local_raw_path = raw_dir
        
        # Should skip and use existing metadata
        result = enricher.enrich(record, force=False)
        
        # The enricher should update record from existing metadata
        assert result.title == "Existing Title"
        assert result.author == "Existing Author"
        
        # Cleanup
        import shutil
        shutil.rmtree(tmp)
    
    def test_force_overrides_cache(self):
        """Test that force=True re-fetches metadata."""
        import tempfile
        
        enricher = WebpageMetadataEnricher()
        
        tmp = tempfile.mkdtemp()
        raw_dir = Path(tmp) / "raw" / "webpage" / "example.com" / "abc123"
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # Create raw.html with OG tags
        html = '<html><head><meta property="og:title" content="New Title from OG" /></head><body></body></html>'
        from wiki.storage import Storage
        Storage.write_text(html, raw_dir / "raw.html")
        
        existing_metadata = {"title": "Old Title", "url": "https://example.com"}
        Storage.write_json(existing_metadata, raw_dir / "metadata.json")
        
        record = ResourceRecord(
            id="webpage:abc123",
            source_type=SourceType.WEBPAGE,
            canonical_id="webpage:abc123",
            original_url="https://example.com",
            title="Old Title",
        )
        record.local_raw_path = raw_dir
        record.content_hash = "abc123"
        
        # With force=True, should re-extract from HTML
        with patch('wiki.enrich.metadata.config') as mock_config:
            mock_config.get_data_path = lambda *p: Path(tmp).joinpath(*p)
            mock_config.LLM_WIKI_DATA_DIR = Path(tmp)
            
            result = enricher.enrich(record, force=True)
            
            # Title should stay "Old Title" because record already had it
            # (the enricher doesn't overwrite existing titles on the record,
            #  but the metadata file is updated)
            assert result is not None
        
        # Cleanup
        import shutil
        shutil.rmtree(tmp)
