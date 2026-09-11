"""Display values without requiring pandas or an image rendering library."""

from .output import RecordedOutput, dataframe_csv


def text(value: str):
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def display(value):
    if isinstance(value, RecordedOutput):
        return value.to_text()
    if hasattr(value, "to_csv"):
        return text(dataframe_csv(value))
    return text(repr(value))
