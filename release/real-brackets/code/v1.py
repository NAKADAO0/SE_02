def is_balanced(text):
    """Return True if the brackets (), [], {} in text are correctly matched.

    Only the six bracket characters are considered; all other characters
    are ignored. An empty string (or a string with no brackets) is balanced.
    A closing bracket that does not match the most recent unmatched opening
    bracket, or any opening bracket left unmatched, makes the result False.
    """
    if text is None:
        return False

    pairs = {')': '(', ']': '[', '}': '{'}
    stack = []

    for char in text:
        if char in '([{':
            stack.append(char)
        elif char in pairs:
            if not stack or stack[-1] != pairs[char]:
                return False
            stack.pop()

    return not stack
