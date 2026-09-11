"""Display values without requiring pandas or an image rendering library."""


def text(value: str):
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def display(value):
    if hasattr(value, "to_csv"):
        index = value.index
        include_index = index.name is not None or type(index).__name__ != "RangeIndex"
        result = value.to_csv(index=include_index, lineterminator="\n")
        if not isinstance(result, str):
            raise TypeError("to_csv must return a string")
        return text(result)
    return text(repr(value))
