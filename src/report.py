from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PyPlagReport:
    status: int
    stdout: str
    stderr: str
    report_path: Path
    report_min_path: Path|None
