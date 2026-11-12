"""Browser rendering placeholders, loader configuration, and CSP."""

import json
import re

from transcript.document import parse
from transcript.html._assets import SCRIPT, STYLE


def test_page_loads_versioned_renderers_with_integrity_and_cache():
    source = (
        'value = 2\n\nif "transcript.md":\n'
        '    r"""# Heading\\n\\nLiteral **markdown**."""\n'
        "    value + 3\n"
    )

    html = parse(source, "browser.py").render_html()

    match = re.search(
        r'<script id="transcript-renderers" type="application/json">(.*?)</script>',
        html,
    )
    assert match is not None
    config = json.loads(match.group(1))
    assert config["cache"] == "transcript-renderers-v1"
    assert [resource["name"] for resource in config["resources"]] == [
        "markdown-it",
        "highlight.js",
        "highlight.js-default",
        "jsdiff",
    ]
    assert all(
        resource["url"].startswith("https://cdn.jsdelivr.net/")
        for resource in config["resources"]
    )
    assert all(
        resource["integrity"].startswith("sha384-") for resource in config["resources"]
    )
    assert '<div class="doc-md" data-tmd-span=' in html
    assert '<code class="doc-code" data-tmd-span=' in html
    assert '<details class="script-block" data-tmd-span=' in html


def test_markdown_source_view_and_review_overlay_are_wired():
    source = 'if "transcript.md":\n    r"""\n    text\n    """\n'
    document = parse(source, "md.py")
    markdown = document.blocks[0].markdown
    assert markdown is not None

    html = document.render_html()
    body = "\n    text\n    "
    body_start = source.index(body)
    body_end = body_start + len(body)

    assert "tmd-md-source" in html
    assert "tmd-md-overlay" in html
    assert "tmd-md-trigger" in html
    assert "tmd-diff-fill" in SCRIPT
    assert "tmd-diff-anchor" in STYLE
    assert "tmd-diff-edit-del" in STYLE
    assert "tmd-diff-last-del" in STYLE
    assert "tmd-diff-next-ins" in STYLE
    assert f'data-tmd-span="{body_start},{body_end}"' in html
    assert source[slice(*markdown)] == body


def test_markdown_renderer_images_keep_their_origins_in_the_image_policy():
    source = (
        'if "transcript.md":\n'
        '    """\n'
        "    prose\n"
        '    """\n'
        '    markdown("![shot](https://shots.example.test/a.png)")\n'
        '    """\n'
        "    ```transcript-output markdown=1\n"
        "    ![shot](https://shots.example.test/a.png)\n"
        "    ```\n"
        '    """\n'
    )

    html = parse(source, "md_images.py").render_html()
    policy = re.search(r"img-src[^;]*", html)

    assert policy is not None
    assert "https://shots.example.test" in policy.group(0)
    assert 'data-tmd-renderer="markdown"' in html

    marker = 'data-tmd-renderer="markdown" data-tmd-span="'
    value = html.split(marker, 1)[1].split('"', 1)[0]
    start, end = (int(part) for part in value.split(","))
    assert source[start:end] == "    ![shot](https://shots.example.test/a.png)"
    assert "data-tmd-slot-start" not in html
