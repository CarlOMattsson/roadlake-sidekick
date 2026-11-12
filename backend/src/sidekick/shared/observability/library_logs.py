"""Constant log templates for third-party loggers that can echo request content.

FastMCP and the MCP SDK interpolate tool arguments, validation inputs and serializer errors
into their messages. Sidekick cannot change those call sites, so the logger itself is wrapped:
every record it emits is replaced by a fixed template, DEBUG is dropped, and no traceback
survives.
"""

import logging
from collections.abc import Iterable


class ConstantTemplateFilter(logging.Filter):
    """Reduce a library record to a fixed message: no arguments, no f-string text, no traceback.

    The label names the source in the fixed message. It is a constant chosen by Sidekick and
    never carries record content.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.INFO:
            return False
        record.msg = f"{self.label} {record.levelname.lower()} record (content withheld)"
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def withhold_record_content(logger_names: Iterable[str], label: str) -> None:
    """Install one `ConstantTemplateFilter` per named logger. Repeat calls add nothing."""

    for name in logger_names:
        library_logger = logging.getLogger(name)
        if not any(
            isinstance(item, ConstantTemplateFilter) and item.label == label
            for item in library_logger.filters
        ):
            library_logger.addFilter(ConstantTemplateFilter(label))
