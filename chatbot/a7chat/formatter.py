"""Answer sentence. Until Vincent decides X-1 (ticket 10), this is a fixed template."""


def template_sentence(row_count: int) -> str:
    if row_count == 0:
        return "No rows matched your question."
    return f"Found {row_count} {'row' if row_count == 1 else 'rows'} for your question."


def truncation_note(row_cap: int) -> str:
    return f"Showing the first {row_cap} rows; there are more. Narrow your question to see the rest."
