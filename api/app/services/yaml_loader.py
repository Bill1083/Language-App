"""YAML loading for curriculum files.

PyYAML follows YAML 1.1, where unquoted `no`, `yes`, `on` and `off` are
booleans. That turned the romaji "no" (の) into False and the French pronoun
"on" into True. This loader only treats true/false as booleans, so curriculum
authors don't have to remember to quote ordinary words.
"""

import re
from pathlib import Path
from typing import Any

import yaml

BOOL_TAG = "tag:yaml.org,2002:bool"


class CurriculumLoader(yaml.SafeLoader):
    pass


CurriculumLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
CurriculumLoader.add_implicit_resolver(
    BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=CurriculumLoader)  # noqa: S506 - SafeLoader subclass


def load_yaml_file(path: Path) -> Any:
    return load_yaml(path.read_text(encoding="utf-8"))
