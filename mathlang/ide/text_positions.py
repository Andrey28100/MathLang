"""Convert language code-point offsets to Qt's UTF-16 cursor positions."""


def qt_position(text: str, offset: int) -> int:
    return len(text[:max(0, min(offset, len(text)))].encode('utf-16-le', errors='surrogatepass')) // 2


def source_position(text: str, position: int) -> int:
    units = 0
    for index, char in enumerate(text):
        if units >= position:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(text)
