# GitOps

Shared Gitea Actions used across Kyle-Spicer's projects. Each is a composite
action; reference one from a workflow by its path on `main`:

```yaml
uses: https://gitea.com/Kyle-Spicer/GitOps/actions/<name>@main
```

Pinning to `@main` means a push to this repository changes the action for
every workflow that uses it, immediately. Pin to a tag or commit SHA instead
if you need a workflow to stay fixed.

## Contents

- [Available actions](#available-actions) - overview table
- [locate-msbuild](#locate-msbuild) - find `MSBuild.exe`
- [msbuild-release](#msbuild-release) - build a VS solution or project
- [upload-build](#upload-build) - upload an artifact
- [userguide-pdf](#userguide-pdf) - render and upload `userguide.pdf`

## Available actions

Each row links to that action's section below; the section heading links to
its source `action.yml`.

| Action | Purpose | Runner OS |
|---|---|---|
| [`locate-msbuild`](#locate-msbuild) | Find the newest `MSBuild.exe` via `vswhere` | Windows |
| [`msbuild-release`](#msbuild-release) | Build a Visual Studio solution or project | Windows |
| [`upload-build`](#upload-build) | Upload build output as a workflow artifact | Any |
| [`userguide-pdf`](#userguide-pdf) | Render `Docs/userguide.md` to a PDF and upload it | Any |

### [locate-msbuild](actions/locate-msbuild/action.yml)

Resolves the path to the newest `MSBuild.exe` on the runner using `vswhere`,
preferring the 64-bit build to avoid WOW64 path redirection. `msbuild-release`
calls this itself, so you only need it directly to run MSBuild your own way.

**Outputs:** `msbuild-path` - the resolved path. Also exported as the
`MSBUILD` environment variable for later steps.

Windows only: uses PowerShell and `vswhere`.

```yaml
- id: msbuild
  uses: https://gitea.com/Kyle-Spicer/GitOps/actions/locate-msbuild@main
- shell: powershell
  run: & "${{ steps.msbuild.outputs.msbuild-path }}" MyApp.sln /p:Configuration=Release
```

### [msbuild-release](actions/msbuild-release/action.yml)

Builds a `.sln`, `.slnx`, or `.vcxproj` with `/m /nologo /restore`. Locates
MSBuild via `locate-msbuild` first.

| Input | Required | Default | Description |
|---|---|---|---|
| `project` | yes | | Path to the `.sln`, `.slnx`, or `.vcxproj`, relative to `working-directory` |
| `configuration` | no | `Release` | `Debug` or `Release` |
| `platform` | no | `x64` | `x64`, `x86`, or `Win32` |
| `working-directory` | no | `.` | Directory to build from |
| `extra-args` | no | `""` | Extra MSBuild arguments, space separated |

**Outputs:** `msbuild-path` - the MSBuild used.

Windows only: uses PowerShell and MSBuild.

```yaml
- uses: https://gitea.com/Kyle-Spicer/GitOps/actions/msbuild-release@main
  with:
    project: MyApp/MyApp.slnx
    configuration: Release
    platform: x64
```

### [upload-build](actions/upload-build/action.yml)

Uploads files, folders, or globs as a workflow artifact, wrapping
`actions/upload-artifact@v4`. Any file type. A path that matches nothing
fails the step.

| Input | Required | Default | Description |
|---|---|---|---|
| `name` | yes | | Artifact name, unique within the workflow run |
| `path` | yes | | Files, folders, or globs, one per line, relative to the repo root. `!` prefix excludes |
| `retention-days` | no | `7` | Days to keep the artifact on Gitea |

**Outputs:** `artifact-id` - the uploaded artifact's ID.

Runs on any runner OS (no shell steps). Needs Node.js on the runner, which
`actions/upload-artifact` requires.

```yaml
- uses: https://gitea.com/Kyle-Spicer/GitOps/actions/upload-build@main
  with:
    name: myapp-windows-x64
    path: |
      build/MyApp.exe
      docs/guide.pdf
      !**/*.pdb
```

Artifacts expire (the Gitea server sets the maximum; `retention-days` can
only shorten it). For downloads that should never expire, attach the files
to a Gitea Release instead.

### [userguide-pdf](actions/userguide-pdf/action.yml)

Renders a repository's user guide to `userguide.pdf` and uploads it with
`upload-build`. Looks for `Docs/userguide.md`, then `docs/userguide.md`.
Images the guide references, such as an `image.png` beside it, must exist,
or the step fails and names the missing file. Links within the guide, like a
table of contents, become working links and PDF bookmarks.

| Input | Required | Default | Description |
|---|---|---|---|
| `name` | no | `userguide` | Artifact name, unique within the workflow run |
| `output` | no | `userguide.pdf` | PDF to write, relative to the repo root |
| `guide` | no | `""` | Guide to render instead of searching `Docs/` and `docs/` |
| `paper-size` | no | `Letter` | Page size, such as `Letter` or `A4` |
| `upload` | no | `"true"` | `"false"` renders only, for example to attach the PDF to a release |
| `retention-days` | no | `7` | Days to keep the artifact on Gitea |

**Outputs:** `pdf-path` - absolute path of the rendered PDF.

Runs on any runner OS. Needs Python 3.10 or newer on the `PATH`, as `python`
on Windows and `python3` elsewhere, plus network access to PyPI. On first use
it installs a pinned renderer (markdown-pdf with PyMuPDF, about 70 MB) into a
private virtual environment in the runner's temp folder and reuses it after
that; the runner's own Python is never changed. A stock Debian or Ubuntu
Python, which lacks pip, works too.

```yaml
- uses: actions/checkout@v4
- uses: https://gitea.com/Kyle-Spicer/GitOps/actions/userguide-pdf@main
```
