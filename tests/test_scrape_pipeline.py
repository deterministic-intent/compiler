"""Test scraping pipeline functionality."""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from scraper.base_scraper import BaseScraper
from scraper.parser_utils import extract_code_blocks, detect_toc
from scraper.normalizer import normalize_content
from scraper.mappers import map_content_to_abstractions
from scraper.dedupe import check_duplicates
from scraper.inserter import insert_nodes
from db.schema import NodeIn


class TestParserUtils:
    """Test parser utilities."""
    
    def test_extract_code_blocks(self):
        """Test code block extraction."""
        from bs4 import BeautifulSoup
        
        html = """
        <html>
            <body>
                <pre><code class="python">def hello(): print("world")</code></pre>
                <code>inline code</code>
                <pre><code class="javascript">console.log("test");</code></pre>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(html, "html.parser")
        code_blocks = extract_code_blocks(soup)
        
        assert len(code_blocks) == 3
        assert code_blocks[0]["language"] == "python"
        assert code_blocks[0]["type"] == "pre_code"
        assert code_blocks[1]["type"] == "inline_code"
        assert code_blocks[2]["language"] == "javascript"
    
    def test_detect_toc(self):
        """Test table of contents detection."""
        from bs4 import BeautifulSoup
        
        html = """
        <html>
            <body>
                <div class="toc">
                    <a href="#section1">Section 1</a>
                    <a href="#section2">Section 2</a>
                </div>
                <h1 id="section1">Section 1</h1>
                <h2 id="section2">Section 2</h2>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(html, "html.parser")
        toc = detect_toc(soup)
        
        assert len(toc) >= 2
        assert any(item["title"] == "Section 1" for item in toc)
        assert any(item["title"] == "Section 2" for item in toc)


class TestNormalizer:
    """Test content normalization."""
    
    def test_normalize_content(self):
        """Test content normalization."""
        parsed_data = {
            "content": "# Function\nThis is a function.\n\n## Example\n```python\ndef test(): pass```",
            "code_blocks": [
                {"content": "def test(): pass", "language": "python", "type": "pre_code"}
            ],
            "url": "https://example.com",
            "title": "Test Page"
        }
        
        chunks = normalize_content(parsed_data, "python")
        
        assert len(chunks) >= 2  # At least one content chunk and one code chunk
        assert any(chunk["node_type"] == "syntax" for chunk in chunks)
        assert any(chunk["language"] == "python" for chunk in chunks)
    
    def test_split_by_headings(self):
        """Test heading-based content splitting."""
        from scraper.normalizer import split_by_headings
        
        content = "# Title\nContent here.\n\n## Subtitle\nMore content.\n\n### Subsubtitle\nFinal content."
        sections = split_by_headings(content)
        
        assert len(sections) == 3
        assert sections[0]["title"] == "Title"
        assert sections[1]["title"] == "Subtitle"
        assert sections[2]["title"] == "Subsubtitle"
    
    def test_determine_node_type(self):
        """Test node type determination."""
        from scraper.normalizer import determine_node_type
        
        # Test syntax detection
        syntax_type = determine_node_type("Function Syntax", "def function(): pass")
        assert syntax_type == "syntax"
        
        # Test capability detection
        capability_type = determine_node_type("API Function", "function api_call()")
        assert capability_type == "capability"
        
        # Test abstraction detection
        abstraction_type = determine_node_type("Design Pattern", "This is a design pattern")
        assert abstraction_type == "abstraction"


class TestMappers:
    """Test content mapping functionality."""
    
    def test_map_content_to_abstractions(self):
        """Test abstraction mapping."""
        content = "def my_function(): pass\nclass MyClass: pass\nfor i in range(10): pass"
        
        abstractions = map_content_to_abstractions(content, "python")
        
        assert "function" in abstractions
        assert "class" in abstractions
        assert "loop" in abstractions
    
    def test_map_content_to_syntax(self):
        """Test syntax mapping."""
        from scraper.mappers import map_content_to_syntax
        
        content = "def func(): pass\n@decorator\ndef decorated(): pass"
        
        syntax_elements = map_content_to_syntax(content, "python")
        
        assert "decorator" in syntax_elements
    
    def test_map_content_to_capabilities(self):
        """Test capability mapping."""
        from scraper.mappers import map_content_to_capabilities
        
        content = "import json\nwith open('file.txt') as f: pass"
        
        capabilities = map_content_to_capabilities(content, "python")
        
        assert "file_io" in capabilities
        assert "serialization" in capabilities


class TestDeduplication:
    """Test deduplication functionality."""
    
    def test_check_duplicates(self):
        """Test duplicate detection."""
        chunks = [
            {
                "title": "Function",
                "content": "def hello(): print('world')",
                "node_type": "syntax",
                "language": "python",
                "tags": ["function", "python"]
            },
            {
                "title": "Function",
                "content": "def hello(): print('world')",  # Duplicate
                "node_type": "syntax",
                "language": "python",
                "tags": ["function", "python"]
            },
            {
                "title": "Different Function",
                "content": "def goodbye(): print('bye')",
                "node_type": "syntax",
                "language": "python",
                "tags": ["function", "python"]
            }
        ]
        
        unique_chunks = check_duplicates(chunks)
        
        assert len(unique_chunks) == 2  # Should remove one duplicate
    
    def test_create_content_hash(self):
        """Test content hashing."""
        from scraper.dedupe import create_content_hash
        
        content1 = "def hello(): print('world')"
        content2 = "def hello(): print('world')"
        content3 = "def goodbye(): print('bye')"
        
        hash1 = create_content_hash(content1)
        hash2 = create_content_hash(content2)
        hash3 = create_content_hash(content3)
        
        assert hash1 == hash2  # Same content, same hash
        assert hash1 != hash3  # Different content, different hash


class TestBaseScraper:
    """Test base scraper functionality."""
    
    @pytest.fixture
    def mock_scraper(self):
        """Create a mock scraper for testing."""
        source_config = {
            "language": "python",
            "name": "Test Source",
            "url": "https://example.com"
        }
        return BaseScraper("python", source_config)
    
    @pytest.mark.asyncio
    async def test_fetch_page(self, mock_scraper):
        """Test page fetching."""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = Mock()
            mock_response.text = "<html><body>Test content</body></html>"
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            content = await mock_scraper.fetch_page("https://example.com")
            
            assert content == "<html><body>Test content</body></html>"
    
    def test_parse_html(self, mock_scraper):
        """Test HTML parsing."""
        html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Main Title</h1>
                <p>Some content</p>
                <pre><code class="python">def test(): pass</code></pre>
            </body>
        </html>
        """
        
        parsed_data = mock_scraper.parse_html(html, "https://example.com")
        
        assert parsed_data["title"] == "Test Page"
        assert "Main Title" in parsed_data["content"]
        assert len(parsed_data["code_blocks"]) >= 1
        assert parsed_data["url"] == "https://example.com"


class TestScrapingPipeline:
    """Test end-to-end scraping pipeline."""
    
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Test the complete scraping pipeline."""
        # Mock the database insertion
        with patch('scraper.inserter.insert_nodes') as mock_insert:
            mock_insert.return_value = None
            
            # Create a test scraper
            source_config = {
                "language": "python",
                "name": "Test Source",
                "url": "https://example.com"
            }
            scraper = BaseScraper("python", source_config)
            
            # Mock the fetch_page method
            scraper.fetch_page = AsyncMock(return_value="""
                <html>
                    <head><title>Python Functions</title></head>
                    <body>
                        <h1>Functions</h1>
                        <p>A function is a reusable block of code.</p>
                        <pre><code class="python">def hello(): print("world")</code></pre>
                    </body>
                </html>
            """)
            
            # Run the scraper
            await scraper.scrape_url("https://example.com")
            
            # Verify that insert_nodes was called
            mock_insert.assert_called_once()
            
            # Verify the content of the call
            call_args = mock_insert.call_args[0][0]
            assert len(call_args) >= 1
            assert any(chunk["language"] == "python" for chunk in call_args)
            assert any(chunk["node_type"] in ["syntax", "concept"] for chunk in call_args)
