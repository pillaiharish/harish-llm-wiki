"""Normalization modules for chunking content."""

import re
from typing import List, Iterator, Dict, Any

from wiki.schemas import YouTubeChunk, WebpageChunk, MarkdownChunk, SourceType


class Chunker:
    """Chunk content into citeable pieces."""
    
    TARGET_WORDS_PER_CHUNK = 500
    MAX_WORDS_PER_CHUNK = 1000
    
    def chunk_youtube_transcript(self, transcript_entries: List[Dict[str, Any]], 
                                  video_id: str, resource_id: str) -> Iterator[YouTubeChunk]:
        """Chunk YouTube transcript entries.
        
        Combines entries into chunks of 500-1000 words while preserving
        timestamp continuity.
        """
        if not transcript_entries:
            return
        
        chunk_id = 0
        current_entries: List[Dict[str, Any]] = []
        current_words = 0
        start_time = transcript_entries[0]['start']
        
        for entry in transcript_entries:
            entry_text = entry['text']
            word_count = len(entry_text.split())
            
            # Start new chunk if we'd exceed max
            if current_words + word_count > self.MAX_WORDS_PER_CHUNK and current_entries:
                # Yield current chunk
                yield self._create_youtube_chunk(
                    current_entries, chunk_id, resource_id, video_id, start_time
                )
                chunk_id += 1
                current_entries = [entry]
                current_words = word_count
                start_time = entry['start']
            else:
                current_entries.append(entry)
                current_words += word_count
            
            # Yield if we have enough words
            if current_words >= self.TARGET_WORDS_PER_CHUNK:
                yield self._create_youtube_chunk(
                    current_entries, chunk_id, resource_id, video_id, start_time
                )
                chunk_id += 1
                current_entries = []
                current_words = 0
        
        # Yield remaining entries
        if current_entries:
            yield self._create_youtube_chunk(
                current_entries, chunk_id, resource_id, video_id, start_time
            )
    
    def _create_youtube_chunk(self, entries: List[Dict[str, Any]], chunk_id: int,
                               resource_id: str, video_id: str, start_time: float) -> YouTubeChunk:
        """Create a YouTubeChunk from transcript entries."""
        text = ' '.join(e['text'] for e in entries)
        start = entries[0]['start']
        duration = sum(e.get('duration', 0) for e in entries)
        end = start + duration
        
        # Create YouTube URL with timestamp
        url = f"https://www.youtube.com/watch?v={video_id}"
        if start > 0:
            url += f"&t={int(start)}s"
        
        return YouTubeChunk(
            resource_id=resource_id,
            chunk_id=f"{resource_id}-c{chunk_id:04d}",
            source_type=SourceType.YOUTUBE,
            text=text,
            start_time=start,
            end_time=end,
            citation_label=f"{start:.1f}s-{end:.1f}s",
            url=url
        )
    
    def chunk_text(self, text: str, resource_id: str, source_type: SourceType,
                   url: str = None, file_path: str = None) -> Iterator[WebpageChunk | MarkdownChunk]:
        """Chunk text content (webpage or markdown).
        
        Splits by paragraphs and sections while maintaining citeability.
        """
        # Split into sections based on headers
        sections = self._split_into_sections(text)
        
        chunk_id = 0
        for section_heading, section_text in sections:
            paragraphs = [p.strip() for p in section_text.split('\n\n') if p.strip()]
            
            current_paragraphs: List[str] = []
            current_words = 0
            start_idx = 0
            
            for i, para in enumerate(paragraphs):
                word_count = len(para.split())
                
                # Check if adding this paragraph would exceed max
                if current_words + word_count > self.MAX_WORDS_PER_CHUNK and current_paragraphs:
                    # Yield current chunk
                    yield self._create_text_chunk(
                        current_paragraphs, chunk_id, resource_id, source_type,
                        section_heading, start_idx, url, file_path
                    )
                    chunk_id += 1
                    current_paragraphs = [para]
                    current_words = word_count
                    start_idx = i
                else:
                    current_paragraphs.append(para)
                    current_words += word_count
                
                # Yield if we have enough words
                if current_words >= self.TARGET_WORDS_PER_CHUNK:
                    yield self._create_text_chunk(
                        current_paragraphs, chunk_id, resource_id, source_type,
                        section_heading, start_idx, url, file_path
                    )
                    chunk_id += 1
                    current_paragraphs = []
                    current_words = 0
            
            # Yield remaining paragraphs
            if current_paragraphs:
                yield self._create_text_chunk(
                    current_paragraphs, chunk_id, resource_id, source_type,
                    section_heading, start_idx, url, file_path
                )
                chunk_id += 1
    
    def _split_into_sections(self, text: str) -> List[tuple[str | None, str]]:
        """Split text into sections based on Markdown headers.
        
        Returns list of (section_heading, section_content) tuples.
        """
        # Pattern to match Markdown headers (# Header)
        header_pattern = r'^(#{1,6}\s+.+)$'
        
        lines = text.split('\n')
        sections: List[tuple[str | None, str]] = []
        current_heading: str | None = None
        current_content: List[str] = []
        
        for line in lines:
            if re.match(header_pattern, line.strip()):
                # Save previous section
                if current_content:
                    sections.append((current_heading, '\n'.join(current_content).strip()))
                
                # Start new section
                current_heading = line.strip().lstrip('#').strip()
                current_content = []
            else:
                current_content.append(line)
        
        # Add final section
        if current_content or current_heading:
            sections.append((current_heading, '\n'.join(current_content).strip()))
        
        # If no sections found, return entire text
        if not sections:
            sections = [(None, text)]
        
        return sections
    
    def _create_text_chunk(self, paragraphs: List[str], chunk_id: int,
                           resource_id: str, source_type: SourceType,
                           section_heading: str | None, start_idx: int,
                           url: str = None, file_path: str = None) -> WebpageChunk | MarkdownChunk:
        """Create a text chunk (Webpage or Markdown)."""
        text = '\n\n'.join(paragraphs)
        
        if source_type == SourceType.WEBPAGE:
            return WebpageChunk(
                resource_id=resource_id,
                chunk_id=f"{resource_id}-c{chunk_id:04d}",
                source_type=SourceType.WEBPAGE,
                text=text,
                section_heading=section_heading,
                paragraph_index=start_idx + 1,  # 1-indexed
                citation_label=section_heading or f"chunk {chunk_id}",
                url=url
            )
        else:
            return MarkdownChunk(
                resource_id=resource_id,
                chunk_id=f"{resource_id}-c{chunk_id:04d}",
                source_type=source_type,
                text=text,
                section_heading=section_heading,
                paragraph_index=start_idx + 1,  # 1-indexed
                citation_label=section_heading or f"chunk {chunk_id}",
                file_path=file_path
            )


# Global instance
chunker = Chunker()
