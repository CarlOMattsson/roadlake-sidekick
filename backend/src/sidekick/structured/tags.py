"""The tag arguments and the tag field of the records that carry the owner's tags.

A tag is one entry of the owner's vocabulary, whatever record it is on (`list_tags`). Contacts and
Journal entries take their tags through these types, so the tools describe them the same way.
"""

from typing import Annotated, Literal

from pydantic import Field

from sidekick.shared.text_guard import NoImageData
from sidekick.work.domain.planning import MAX_TAG_FILTER_VALUES, MAX_TAGS_PER_RECORD

TagMatch = Literal["any", "all"]

TagsInput = Annotated[
    list[Annotated[str, NoImageData]],
    Field(
        max_length=MAX_TAGS_PER_RECORD,
        description=(
            "Complete tag set, e.g. 'viktig', 'vänta', 'familj'; replaces the current set, "
            "[] clears it."
        ),
    ),
]

TagFilter = Annotated[list[str], Field(max_length=MAX_TAG_FILTER_VALUES)]
