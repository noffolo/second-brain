import os
import tempfile
import yaml
from engine.utils.markdown import parse_markdown, to_markdown, extract_wikilinks, load_settings

def test_parse_markdown_with_frontmatter():
    content = "---\ntitle: Test Page\ntags: [test, debug]\n---\n# Header\nThis is a body."
    fm, body = parse_markdown(content)
    assert fm == {"title": "Test Page", "tags": ["test", "debug"]}
    assert body.strip() == "# Header\nThis is a body."

def test_parse_markdown_without_frontmatter():
    content = "# Header\nThis is a body without frontmatter."
    fm, body = parse_markdown(content)
    assert fm == {}
    assert body == content

def test_to_markdown():
    fm = {"title": "Hello", "category": "Test"}
    body = "World!"
    markdown = to_markdown(fm, body)
    assert markdown.startswith("---\n")
    assert "title: Hello" in markdown
    assert "category: Test" in markdown
    assert markdown.endswith("\nWorld!")

def test_extract_wikilinks():
    text = "Here is a link to [[Machine Learning]] and [[Deep Learning|DL]]. What about a broken one [[Test]]?"
    links = extract_wikilinks(text)
    assert len(links) == 3
    assert "Machine Learning" in links
    assert "Deep Learning" in links
    assert "Test" in links

    # Test nested brackets in wikilinks (e.g. [in serata])
    text_nested = "Test [[Algorave [in serata]]] e [[Raccordo Sito web [Leti]|Raccordo]]"
    links_nested = extract_wikilinks(text_nested)
    assert len(links_nested) == 2
    assert "Algorave [in serata]" in links_nested
    assert "Raccordo Sito web [Leti]" in links_nested

    # Test YAML double single quotes escaping in frontmatter
    yaml_escaped_content = "---\nrelated:\n- '[[Ritiro carta d''identità]]'\n---\n# Body [[Algorave]]"
    links_yaml = extract_wikilinks(yaml_escaped_content)
    assert len(links_yaml) == 2
    assert "Ritiro carta d'identità" in links_yaml
    assert "Algorave" in links_yaml

def test_load_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path = os.path.join(tmpdir, "settings.md")
        
        # Test default load when file does not exist
        settings = load_settings(tmpdir)
        assert settings["timing"]["sync_and_ingest"] == "3600"
        
        # Write custom settings
        custom_content = "---\ntiming:\n  sync_and_ingest: 1800\n  weekly_reflection: '0 12 * * 6'\n---"
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(custom_content)
            
        settings = load_settings(tmpdir)
        assert settings["timing"]["sync_and_ingest"] == 1800
        assert settings["timing"]["weekly_reflection"] == "0 12 * * 6"
