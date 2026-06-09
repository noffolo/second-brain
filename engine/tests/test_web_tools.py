import os
from engine.tools.web_tools import url_to_filename, clean_raw_html

def test_url_to_filename():
    url = "https://www.example.com/p/some-article-slug?param=val"
    filename = url_to_filename(url)
    assert filename == "www_example_com_p_some_article_slug_param_val.md"

def test_clean_raw_html():
    raw_html = """
    <html>
      <head><title>Test</title></head>
      <body>
        <nav>Navigation menu</nav>
        <script>console.log('hello');</script>
        <style>body { color: red; }</style>
        <h1>Main Content</h1>
        <p>This is the actual text.</p>
        <footer>Footer info</footer>
      </body>
    </html>
    """
    cleaned = clean_raw_html(raw_html)
    assert "console.log" not in cleaned
    assert "Navigation menu" not in cleaned
    assert "Main Content" in cleaned
    assert "This is the actual text" in cleaned
