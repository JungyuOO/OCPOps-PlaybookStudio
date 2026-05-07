import html
from functools import lru_cache
from pathlib import Path


def _asset_path(name: str) -> Path:
    return Path(__file__).with_name(name)


@lru_cache(maxsize=1)
def _viewer_page_css() -> str:
    return _asset_path("viewer_page.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _viewer_page_js() -> str:
    return _asset_path("viewer_page.js").read_text(encoding="utf-8")


def _render_study_viewer_html(
    *,
    title: str,
    source_url: str,
    cards: list[str],
    supplementary_blocks: list[str] | None = None,
    section_count: int,
    eyebrow: str,
    summary: str,
    embedded: bool = False,
    page_overlay_toolbar: str = "",
    section_outline: list[dict[str, str]] | None = None,
    section_navigation: list[dict[str, str]] | None = None,
    section_metrics: list[str] | None = None,
) -> str:
    hero_block = ""
    embedded_meta_block = ""
    document_class = "study-document"
    hero_meta_block = ""
    document_toolbar_block = ""
    document_footer_navigation_block = ""
    summary_block = f'<p class="summary">{html.escape(summary)}</p>' if summary else ""
    hero_metric_pills = "".join(
        '<span class="meta-pill">{}</span>'.format(html.escape(metric))
        for metric in (section_metrics or [])
        if str(metric).strip()
    )
    toolbar_items: list[str] = []
    if section_outline:
        nav_links = "".join(
            """
            <a class="document-nav-link" href="#{anchor}" title="{path}">{heading}</a>
            """.format(
                anchor=html.escape(str(item.get("anchor") or ""), quote=True),
                path=html.escape(str(item.get("path") or "")),
                heading=html.escape(str(item.get("heading") or "")),
            ).strip()
            for item in section_outline
            if str(item.get("anchor") or "").strip() and str(item.get("heading") or "").strip()
        )
        if nav_links:
            toolbar_items.append(
                """
                <details class="document-nav-menu">
                  <summary class="document-nav-trigger">Quick Nav</summary>
                  <div class="document-nav-popover">
                    <div class="document-nav-links">{nav_links}</div>
                  </div>
                </details>
                """.format(nav_links=nav_links).strip()
            )
    if section_navigation:
        navigation_items = [
            {
                "label": str(item.get("label") or "").strip(),
                "href": str(item.get("href") or "").strip(),
                "title": str(item.get("title") or "").strip(),
            }
            for item in section_navigation
            if str(item.get("href") or "").strip() and str(item.get("label") or "").strip()
        ]
        previous_item = next((item for item in navigation_items if item["label"] == "이전"), None)
        next_item = next((item for item in navigation_items if item["label"] == "다음"), None)
        previous_link = (
            '<a class="document-section-nav-link document-section-nav-link-previous" href="{href}" title="{title}">{label}</a>'.format(
                href=html.escape(str(item.get("href") or ""), quote=True),
                title=html.escape(str(item.get("title") or "")),
                label=html.escape(str(item.get("label") or "")),
            )
            if (item := previous_item) is not None
            else ""
        )
        next_link = (
            '<a class="document-section-nav-link document-section-nav-link-next" href="{href}" title="{title}">{label}</a>'.format(
                href=html.escape(str(item.get("href") or ""), quote=True),
                title=html.escape(str(item.get("title") or "")),
                label=html.escape(str(item.get("label") or "")),
            )
            if (item := next_item) is not None
            else ""
        )
        if previous_link or next_link:
            document_footer_navigation_block = """
              <div class="document-footer-nav">
                <div class="document-footer-nav-slot document-footer-nav-slot-start">{previous_link}</div>
                <div class="document-footer-nav-slot document-footer-nav-slot-end">{next_link}</div>
              </div>
            """.format(previous_link=previous_link, next_link=next_link)
    if page_overlay_toolbar:
        toolbar_items.append(page_overlay_toolbar)
    if toolbar_items:
        document_toolbar_block = """
          <div class="document-toolbar">
            {toolbar_items}
          </div>
        """.format(toolbar_items="".join(toolbar_items))
    if not embedded:
        hero_meta_block = """
            <div class="hero-meta">
              {hero_metric_pills}
              <span class="meta-pill meta-pill-accent">{eyebrow}</span>
            </div>
        """
        hero_block = """
          <section class="hero">
            <div class="hero-grid">
                <div class="hero-main">
                  <div class="eyebrow">{eyebrow}</div>
                  <h1>{title}</h1>
                  {summary_block}
                </div>
              <div class="actions hero-actions">
                {hero_meta_block}
              </div>
            </div>
          </section>
        """
    else:
        document_class = "study-document study-document-embedded"
        if document_toolbar_block:
            embedded_meta_block = document_toolbar_block
    article_toolbar_block = document_toolbar_block if document_toolbar_block else embedded_meta_block
    extra_blocks = "\n".join(supplementary_blocks or [])
    reader_sidebar = ""
    if extra_blocks and not embedded:
        reader_sidebar = '<aside class="reader-sidebar">{}</aside>'.format(extra_blocks)
        extra_blocks = ""
    return """
    <!DOCTYPE html>
    <html lang="ko">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title} - OCP 출처 뷰어</title>
        <style>{page_css}</style>
      </head>
      <body class="{body_class}">
        <main>
          {hero_block}
          <section class="reader-layout">
            <div class="reader-main">
              <article class="{document_class}">
                {article_toolbar_block}
                {extra_blocks}
                <div class="section-list">
                  {cards}
                </div>
                {document_footer_navigation_block}
              </article>
            </div>
            {reader_sidebar}
          </section>
        </main>
        <script>{page_js}</script>
      </body>
    </html>
    """.format(
        title=html.escape(title),
        page_css=_viewer_page_css(),
        page_js=_viewer_page_js(),
        eyebrow=html.escape(eyebrow),
        summary=html.escape(summary),
        summary_block=summary_block,
        section_count=section_count,
        source_url=html.escape(source_url, quote=True),
        body_class="is-embedded" if embedded else "",
        document_class=document_class,
        extra_blocks=extra_blocks,
        reader_sidebar=reader_sidebar,
        document_footer_navigation_block=document_footer_navigation_block,
        article_toolbar_block=article_toolbar_block or "",
        hero_metric_pills=hero_metric_pills,
        hero_meta_block=hero_meta_block.format(
            eyebrow=html.escape(eyebrow),
            hero_metric_pills=hero_metric_pills,
        ) if hero_meta_block else "",
        hero_block=hero_block.format(
            title=html.escape(title),
            eyebrow=html.escape(eyebrow),
            summary=html.escape(summary),
            summary_block=summary_block,
            hero_meta_block=hero_meta_block.format(
                eyebrow=html.escape(eyebrow),
                hero_metric_pills=hero_metric_pills,
            ) if hero_meta_block else "",
        ) if hero_block else "",
        cards="\n".join(cards),
    ).strip()


__all__ = ["_render_study_viewer_html"]
