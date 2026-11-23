"""The refusals of the library rules.

A refusal carries a closed `refusal` code and a message that is that same code, never a part of
the text, address or title that was refused, so it is safe to log and to show.
"""

from sidekick.shared.errors import ValidationError


class LibraryRefusedError(ValidationError):
    """An input the library rules do not accept. `refusal` names why, in a fixed vocabulary."""

    code = "library_refused"
    safe_title = "The library refused the request"

    def __init__(self, refusal: str) -> None:
        super().__init__(refusal)
        self.refusal = refusal
