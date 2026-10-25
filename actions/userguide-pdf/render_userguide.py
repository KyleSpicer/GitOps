"""Renders a repository's userguide.md to userguide.pdf.

Finds Docs/userguide.md or docs/userguide.md, checks that every local image it
references exists, and renders it with markdown-pdf (PyMuPDF), which installs
from pip with no system libraries on Windows, Linux, or macOS.

Run with any Python 3.10+. When markdown-pdf is not importable, the script
creates a private virtual environment, installs the pinned versions below into
it, and re-runs itself there, so the runner's own Python is never modified.
That works on a stock Debian or Ubuntu Python too, which ships without pip or
ensurepip.
"""

import argparse
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request
import venv

#: Exact versions, so every runner renders the same way. PyMuPDF 2.x pulls in
#: onnxruntime and numpy for layout analysis this action does not use.
REQUIREMENTS = ["markdown-pdf==1.13.3", "PyMuPDF==1.28.2"]

#: Set in the re-run inside the private environment, so a failed install
#: cannot loop forever.
BOOTSTRAPPED_ENV = "USERGUIDE_PDF_BOOTSTRAPPED"

#: Written into the environment after a successful install. A missing or
#: different marker means a half-built or outdated environment: rebuild it.
READY_MARKER = "userguide-pdf-requirements.txt"

#: The Python Packaging Authority's pip installer, for a Python without
#: ensurepip (Debian and Ubuntu move it into the separate python3-venv package).
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

#: Where to look for the guide, relative to the repository root, in order.
GUIDE_CANDIDATES = ["Docs/userguide.md", "docs/userguide.md"]

#: Markdown images and HTML <img> tags; the captured group is the source.
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)|<img[^>]*\bsrc=\"([^\"]+)\"")

STYLESHEET = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.4; }
h1 { font-size: 22pt; }
h2 { font-size: 16pt; margin-top: 18pt; }
h3 { font-size: 13pt; }
table { border-collapse: collapse; margin: 6pt 0; }
th, td { border: 1px solid #999999; padding: 3pt 6pt; text-align: left; }
th { background-color: #eeeeee; }
pre, code { font-family: monospace; font-size: 9pt; }
pre { background-color: #f4f4f4; padding: 6pt; }
"""


def _venv_python(venv_dir: pathlib.Path) -> pathlib.Path:
    """Returns the interpreter path inside a virtual environment."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _build_environment(venv_dir: pathlib.Path, python: pathlib.Path) -> None:
    """Creates a fresh environment and installs the pinned renderer into it.

    :param venv_dir: Where to create the environment; replaced if present.
    :param python: The environment's interpreter, once created.
    """
    has_ensurepip = importlib.util.find_spec("ensurepip") is not None
    print(f"Creating environment in {venv_dir}", flush=True)
    venv.create(venv_dir, clear=True, with_pip=has_ensurepip)

    if not has_ensurepip:
        get_pip = venv_dir / "get-pip.py"
        print(
            f"No ensurepip in this Python; installing pip from {GET_PIP_URL}",
            flush=True,
        )
        urllib.request.urlretrieve(GET_PIP_URL, get_pip)
        subprocess.run([str(python), str(get_pip), "--quiet"], check=True)

    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
        + REQUIREMENTS,
        check=True,
    )


def _ensure_renderer() -> None:
    """Re-runs this script in a private environment if markdown-pdf is absent.

    Does not return when it re-runs: the child's exit code becomes this
    process's exit code.
    """
    if importlib.util.find_spec("markdown_pdf") is not None:
        return

    if os.environ.get(BOOTSTRAPPED_ENV):
        sys.exit("markdown-pdf is still missing after installing it")

    base = pathlib.Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    venv_dir = base / "userguide-pdf-venv"
    python = _venv_python(venv_dir)
    marker = venv_dir / READY_MARKER
    wanted = "\n".join(REQUIREMENTS)

    if not (marker.is_file() and marker.read_text(encoding="utf-8") == wanted):
        _build_environment(venv_dir, python)
        marker.write_text(wanted, encoding="utf-8")

    env = dict(os.environ, **{BOOTSTRAPPED_ENV: "1"})
    result = subprocess.run([str(python), *sys.argv], env=env, check=False)
    sys.exit(result.returncode)


def _find_guide(root: pathlib.Path, explicit: str) -> pathlib.Path:
    """Locates the guide, preferring an explicit path when one is given.

    :param root: Repository root.
    :param explicit: Path from the caller, or empty to search the defaults.
    :return: Path to the guide.
    """
    candidates = [explicit] if explicit else GUIDE_CANDIDATES

    for candidate in candidates:
        path = root / candidate
        if path.is_file():
            return path

    sys.exit(f"No user guide found; looked for: {', '.join(candidates)}")


def _check_images(guide: pathlib.Path, text: str) -> None:
    """Fails with a clear message if a local image the guide uses is missing.

    :param guide: Path to the guide; image paths are relative to its folder.
    :param text: The guide's Markdown.
    """
    missing = []

    for match in IMAGE_PATTERN.finditer(text):
        source = match.group(1) or match.group(2)
        if re.match(r"[a-z]+://", source) or source.startswith("data:"):
            continue
        if not (guide.parent / source).is_file():
            missing.append(source)

    if missing:
        sys.exit(f"{guide}: missing image(s) next to the guide: {', '.join(missing)}")


def _slug(heading: str) -> str:
    """Makes a GitHub/Gitea-style anchor from a heading's text.

    Lowercase, punctuation dropped, spaces to hyphens, so the guide's own
    ``[...](#getting-started)`` links resolve in the PDF the same way they do
    when Gitea renders the Markdown.
    """
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def _add_heading_ids(parser) -> None:
    """Adds an ``id`` to every heading so in-document links have a target.

    markdown-pdf renders with plain markdown-it, which emits headings without
    ids, and PyMuPDF refuses to save a link that points nowhere. Repeated
    headings get ``-1``, ``-2`` suffixes, matching GitHub.

    :param parser: The MarkdownIt instance markdown-pdf renders with.
    """

    def assign_ids(state) -> None:
        """Core rule: sets ids from each heading's inline text."""
        seen: dict = {}

        for index, token in enumerate(state.tokens):
            if token.type != "heading_open":
                continue

            slug = _slug(state.tokens[index + 1].content)
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            token.attrSet("id", slug if count == 0 else f"{slug}-{count}")

    parser.core.ruler.push("heading_ids", assign_ids)


def _title_of(text: str, fallback: str) -> str:
    """Returns the guide's first level-one heading, for the PDF metadata."""
    match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return match.group(1) if match else fallback


def main() -> None:
    """Parses arguments, renders the PDF, and reports where it was written."""
    # Defaults come from the environment so the action can pass every input
    # without quoting: Windows PowerShell 5.1 drops empty string arguments.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--guide",
        default=os.environ.get("USERGUIDE_GUIDE", ""),
        help="Guide path; default searches Docs/ and docs/",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("USERGUIDE_OUTPUT") or "userguide.pdf",
        help="PDF to write",
    )
    parser.add_argument(
        "--paper-size",
        default=os.environ.get("USERGUIDE_PAPER_SIZE") or "Letter",
        help="Letter, A4, and so on",
    )
    args = parser.parse_args()

    _ensure_renderer()

    # Imported here, not at the top: it exists only once _ensure_renderer has
    # installed it into the private environment.
    from markdown_pdf import (  # pylint: disable=import-outside-toplevel,import-error
        MarkdownPdf,
        Section,
    )

    # resolve() also restores the folder's real case on Windows, so the log
    # names docs/ or Docs/ as it actually is.
    root = pathlib.Path.cwd().resolve()
    guide = _find_guide(root, args.guide).resolve()
    text = guide.read_text(encoding="utf-8")
    _check_images(guide, text)

    pdf = MarkdownPdf(toc_level=2, optimize=True)
    _add_heading_ids(pdf.m_d)
    pdf.meta["title"] = _title_of(text, guide.stem)
    pdf.add_section(
        Section(text, root=str(guide.parent), paper_size=args.paper_size),
        user_css=STYLESHEET,
    )

    output = (root / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(output))
    print(f"Rendered {guide.relative_to(root)} -> {output}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"pdf-path={output}\n")


if __name__ == "__main__":
    main()
