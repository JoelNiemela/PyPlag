from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PyPlagSettings:
    java_cmd: str = "java"
    jplag_jar: Path = Path("./dependencies/jplag.jar")

    report_dir: Path = Path("./reports")

    clustering: bool = True
    filter_runs_by_author: bool = False
    ignore_unsupported_language: bool = False
