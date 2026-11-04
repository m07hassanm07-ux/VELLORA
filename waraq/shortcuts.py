"""Safe, portable keyboard-shortcut validation."""
from PySide6.QtGui import QKeySequence


def portable_shortcut(value: str | QKeySequence) -> str:
    sequence = value if isinstance(value, QKeySequence) else QKeySequence.fromString(str(value), QKeySequence.SequenceFormat.PortableText)
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


def validate_shortcut_map(values: dict[str, str | QKeySequence]) -> dict[str, str]:
    normalized = {str(key): portable_shortcut(value) for key, value in values.items()}
    owners: dict[str, str] = {}
    for key, shortcut in normalized.items():
        identity = shortcut.casefold()
        if not identity:
            continue
        if identity in owners:
            raise ValueError(f"الاختصار {shortcut} مستخدم لأمرين: {owners[identity]} و{key}.")
        owners[identity] = key
    return normalized
