def unique_in_order(values):
    """Return a new list with duplicates removed, keeping first-occurrence order.

    The input list is not modified. An empty input yields an empty list.
    """
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
