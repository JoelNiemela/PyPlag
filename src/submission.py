from dataclasses import dataclass

@dataclass(frozen=True)
class PyPlagSubmission:
    id: str
    lang: str
    author: str
    files: dict[str, str]
