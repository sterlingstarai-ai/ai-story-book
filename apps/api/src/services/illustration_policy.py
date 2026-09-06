"""Image request ceilings shared by generation and prepublication review."""


def max_repair_pages(body_page_count: int) -> int:
    """A full twelve-page book may repair three; shorter books retain two."""
    return 3 if body_page_count == 12 else 2


def book_image_request_limit(body_page_count: int) -> int:
    """Initial cover/pages and all transient retries/quality repairs share one pool."""
    return body_page_count + 1 + max_repair_pages(body_page_count)
