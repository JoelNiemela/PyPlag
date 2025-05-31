#! /bin/env python3

import sys
import json
import subprocess
from tempfile import TemporaryDirectory
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from shutil import rmtree
from subprocess import PIPE, CompletedProcess
from zipfile import ZIP_DEFLATED, ZipFile

from exception import PyPlagException
from report import PyPlagReport
from settings import PyPlagSettings
from submission import PyPlagSubmission

class PyPlag:
    def __init__(
        self,
        settings: PyPlagSettings,
    ) -> None:
        self.settings = settings

        if self.settings.report_dir.exists():
            rmtree(self.settings.report_dir)

        self.supported_languages: list[str] = [
            "c",
            "cpp",
            "csharp",
            "emf",
            "emf-model",
            "go",
            "java",
            "javascript",
            "kotlin",
            "llvmir",
            "multi",
            "python3",
            "rlang",
            "rust",
            "scala",
            "scheme",
            "scxml",
            "swift",
            "text",
            "typescript",
        ]

    def run(self, lang: str, submissions: list[PyPlagSubmission]) -> PyPlagReport:
        if lang not in self.supported_languages:
            if not self.settings.ignore_unsupported_language:
                raise PyPlagException(f"Attempted to run JPlag on submissions in unsupported language '{lang}'")

        self.settings.report_dir.mkdir(exist_ok=True, parents=True)

        if len(submissions) <= 1:
            raise PyPlagException("Too few submissions")

        with TemporaryDirectory(prefix="pyplag-subs-") as tmpfile_path:
            submissions_dir: Path = Path(tmpfile_path)
            for submission in submissions:
                (submissions_dir / submission.id).mkdir(parents=True)

                for filename, file_content in submission.files.items():
                    with open(submissions_dir / submission.id / filename, "w") as file:
                        file.write(file_content)

            extra_args: list[str] = []
            if not self.settings.clustering:
                extra_args.append("--cluster-skip")

            self.settings.report_dir.mkdir(exist_ok=True, parents=True)
            report: Path = self.settings.report_dir / f"{lang}.jplag"

            result = subprocess.run(
                [
                    self.settings.java_cmd,
                    "-jar",
                    self.settings.jplag_jar,
                    "-l",
                    lang,
                    "-M",
                    "RUN",
                    "-r",
                    report,
                    *extra_args,
                    submissions_dir,
                ],
                stdout=PIPE,
                stderr=PIPE,
                text=True,
            )

            report_min: Path | None = None

            if result.returncode == 0:
                if self.settings.filter_runs_by_author:
                    report, report_min = self._post_process_jplag_results(report, submissions)

            return PyPlagReport(
                status=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                report_path=report,
                report_min_path=report_min,
            )

    def _post_process_jplag_results(self, report: Path, submissions: list[PyPlagSubmission]) -> None:
        """
        This is an experimental feature to exclude plagiarism reports from submissions made by the same author.
        """
        submissions_dict: dict[str, PyPlagSubmission] = {
            submission.id: submission for submission in submissions
        }

        report_min: Path = report.with_stem(f"{report.stem}.min")

        with TemporaryDirectory(prefix="pyplag-") as tmpfile_path:
            tmpfile: Path = Path(tmpfile_path)

            with ZipFile(report) as zip_file:
                zip_file.extractall(tmpfile)

            overview: dict
            with open(tmpfile / "overview.json") as file:
                overview = json.load(file)

            ignore_files: list[str] = [
                "basecode",
                "files",
                "options.json",
                "overview.json",
                "README.txt",
                "submissionFileIndex.json",
            ]
            for file_path in tmpfile.iterdir():
                # We only want to loop through the .json files for the pair-wise comparisons; skip other files
                if file_path.name in ignore_files:
                    continue

                submission_id1, submission_id2 = file_path.stem.split("-")
                submission1: PyPlagSubmission = submissions_dict[submission_id1]
                submission2: PyPlagSubmission = submissions_dict[submission_id2]

                if submission1.author == submission2.author:
                    file_data: dict
                    with open(file_path, "r+") as file:
                        file_data = json.load(file)
                        file.write(
                            json.dumps(
                                {
                                    "id1": submission_id1,
                                    "id2": submission_id2,
                                    "similarities": {
                                        "MAX": 0.0,
                                        "AVG": 0.0,
                                    },
                                    "matches": [],
                                    "first_similarity": 0.0,
                                    "second_similarity": 0.0,
                                }
                            )
                        )
                    file_path.unlink()

                    try:
                        del overview["submission_ids_to_comparison_file_name"][submission_id1][submission_id2]
                        del overview["submission_ids_to_comparison_file_name"][submission_id2][submission_id1]
                        pass
                    except KeyError:
                        pass

                    # Constant defined in JPlag
                    SIMILARITY_DISTRIBUTION_SIZE = 100
                    # Correct the MAX and AVG metrics; we can't correct the MIN and INTERSECTION metrics,
                    # as they're missing from the comparison-files, but they appear to be unused.
                    for metric in ["MAX", "AVG"]:
                        # This should behave simlarly to calculateDistributionFor in JPlagResult.java
                        overview["distributions"][metric][
                            min(
                                int(file_data["similarities"][metric] * SIMILARITY_DISTRIBUTION_SIZE),
                                SIMILARITY_DISTRIBUTION_SIZE - 1,
                            )
                        ] -= 1

                    def filter_comparison(comp: dict) -> bool:
                        if (comp["first_submission"] == submission_id1 and comp["second_submission"] == submission_id2) or (
                            comp["first_submission"] == submission_id2 and comp["second_submission"] == submission_id1
                        ):
                            return False

                        return True

                    overview["top_comparisons"] = list(filter(filter_comparison, overview["top_comparisons"]))

                # TODO: Parse the remaining files to see if JPlag has detected any plagiarisms
                # and compile a report of the offending submissions.

            with open(tmpfile / "overview.json", "w") as file:
                file.write(json.dumps(overview))

            # Zip the results, overwriting the original .jplag report.
            # We need to use ZIP_DEFLATED to generate zip v2.0 files, for JPlag compatability.
            with ZipFile(report_min, "w", compression=ZIP_DEFLATED) as zip_file:
                for current_path, subfolders, filenames in tmpfile.walk():
                    for filename in filenames:
                        file_path = current_path / filename
                        arcname = file_path.relative_to(tmpfile)
                        zip_file.write(file_path, arcname)

        return report, report_min

def main() -> None:
    pyplag: PyPlag = PyPlag(PyPlagSettings(
        java_cmd="/usr/lib/jvm/java-21-openjdk/bin/java",
        filter_runs_by_author=True,
    ))

    file = """
        def main() -> None:
            message: str = f"Hello, {input()}"
            times: int = int(input())
            for i in range(times):
                print(message)

        if __name__ == "__main__":
            main()
    """

    print(pyplag.run('python3', [
        PyPlagSubmission("one", "t1", "python3", { "main.py": file }),
        PyPlagSubmission("two", "t1", "python3", { "main.py": file }),
    ]))

if __name__ == "__main__":
    main()
