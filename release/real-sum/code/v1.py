def total(values):
    """Return the sum of all integers in ``values``.

    An empty list yields 0. The function is pure: it does not mutate the
    input, print, perform I/O, or rely on external dependencies.
    """
    result = 0
    for value in values:
        result += value
    return result
