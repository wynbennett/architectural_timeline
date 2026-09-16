"""Build the per-tag file inventory and the context snippets fed to the tier prompts."""
from __future__ import annotations

import fnmatch
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..config import Config
from .workspace import Workspace

EXCLUDED_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", "target", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    "coverage", ".idea", ".vscode", "third_party", "thirdparty", "bower_components",
    ".terraform", "Pods", "DerivedData",
}
EXCLUDED_GLOBS = [
    "*.min.js", "*.min.css", "*.map", "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "go.sum", "*.snap", "*.pb.go", "*_pb2.py",
    "*.generated.*", "*.bundle.js",
]
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp", ".tiff", ".pdf", ".zip",
    ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".jar", ".war", ".class", ".so", ".dylib",
    ".dll", ".exe", ".bin", ".o", ".a", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3",
    ".mp4", ".mov", ".wav", ".ogg", ".flac", ".psd", ".ai", ".sketch", ".fig", ".pyc",
    ".wasm", ".db", ".sqlite", ".parquet", ".npy", ".pkl", ".h5", ".onnx", ".pt",
}
LANGUAGE_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".php": "php", ".cs": "csharp", ".cpp": "cpp",
    ".cc": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp", ".swift": "swift", ".scala": "scala",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".sql": "sql", ".html": "html",
    ".css": "css", ".scss": "scss", ".less": "less", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".md": "markdown", ".rst": "markdown", ".txt": "plaintext",
    ".xml": "xml", ".proto": "protobuf", ".graphql": "graphql", ".tf": "hcl", ".vue": "vue",
    ".svelte": "svelte", ".dockerfile": "dockerfile", ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang", ".hs": "haskell", ".lua": "lua", ".r": "r", ".dart": "dart",
}
MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile",
    "composer.json", "mix.exs", "Procfile", "serverless.yml", "serverless.yaml", "vercel.json",
    "fly.toml", "render.yaml", "app.yaml", "Makefile", "CMakeLists.txt",
}
MANIFEST_GLOBS = ["Dockerfile*", "docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml"]
K8S_DIR_HINTS = {"k8s", "kubernetes", "helm", "charts", "deploy", "deployment", "manifests", "infra"}
ENTRYPOINT_STEMS = {"main", "app", "server", "index", "cli", "manage", "wsgi", "asgi", "application", "bootstrap", "run"}


def language_for(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.name.lower().startswith("dockerfile"):
        return "dockerfile"
    if p.name == "Makefile":
        return "makefile"
    return LANGUAGE_BY_EXT.get(p.suffix.lower())


def is_excluded(path: str, size: int, max_bytes: int) -> bool:
    parts = PurePosixPath(path).parts
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    if any(fnmatch.fnmatch(name, g) for g in EXCLUDED_GLOBS):
        return True
    if PurePosixPath(name).suffix.lower() in BINARY_EXT:
        return True
    if size > max_bytes or size <= 0:
        return True
    return False


@dataclass
class InventoryFile:
    path: str
    size: int
    language: str | None


@dataclass
class Inventory:
    sha: str
    files: list[InventoryFile]
    by_path: dict[str, InventoryFile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_path = {f.path: f for f in self.files}

    def has(self, path: str) -> bool:
        return path in self.by_path

    def under(self, prefixes: list[str]) -> list[InventoryFile]:
        """Files whose path equals a prefix or lives under a prefix directory."""
        out: list[InventoryFile] = []
        norm = [p.strip("/") for p in prefixes if p.strip("/")]
        for f in self.files:
            for p in norm:
                if f.path == p or f.path.startswith(p + "/"):
                    out.append(f)
                    break
        return out

    def path_exists(self, candidate: str) -> bool:
        """True if candidate is an inventory file or a directory prefix of one."""
        c = candidate.strip("/")
        if not c:
            return False
        if c in self.by_path:
            return True
        return any(f.path.startswith(c + "/") for f in self.files)


def build_inventory(ws: Workspace, max_bytes: int | None = None) -> Inventory:
    max_bytes = max_bytes or Config.MAX_FILE_BYTES
    files = [
        InventoryFile(path=path, size=size, language=language_for(path))
        for path, size in ws.list_files()
        if not is_excluded(path, size, max_bytes)
    ]
    files.sort(key=lambda f: f.path)
    return Inventory(sha=ws.sha, files=files)


# ---------- context builders (text handed to the prompts) ----------

def read_text(ws: Workspace, path: str) -> str:
    return ws.read(path)


def head_lines(text: str, n: int) -> str:
    lines = text.splitlines()
    head = "\n".join(lines[:n])
    if len(lines) > n:
        head += f"\n... ({len(lines) - n} more lines)"
    return head


def numbered(text: str) -> str:
    return "\n".join(f"{i + 1:5d}  {line}" for i, line in enumerate(text.splitlines()))


def directory_tree(inv: Inventory, max_depth: int = 3, max_entries: int = 400) -> str:
    """Depth-limited tree with file counts and dominant language per directory."""
    counts: dict[str, int] = defaultdict(int)
    langs: dict[str, Counter] = defaultdict(Counter)
    children: dict[str, set[str]] = defaultdict(set)
    files_at: dict[str, list[str]] = defaultdict(list)

    for f in inv.files:
        parts = PurePosixPath(f.path).parts
        dirs = parts[:-1]
        for depth in range(len(dirs) + 1):
            d = "/".join(dirs[:depth])
            counts[d] += 1
            if f.language:
                langs[d][f.language] += 1
        for depth in range(1, len(dirs) + 1):
            parent = "/".join(dirs[: depth - 1])
            children[parent].add("/".join(dirs[:depth]))
        files_at["/".join(dirs)].append(parts[-1])

    lines: list[str] = []

    def render(d: str, depth: int) -> None:
        if len(lines) >= max_entries:
            return
        label = d.rsplit("/", 1)[-1] if d else "."
        lang = langs[d].most_common(1)[0][0] if langs[d] else "-"
        lines.append(f"{'  ' * depth}{label}/  ({counts[d]} files, {lang})")
        if depth >= max_depth:
            return
        for child in sorted(children[d]):
            render(child, depth + 1)
        if depth < max_depth:
            shown = sorted(files_at[d])[:12]
            for name in shown:
                lines.append(f"{'  ' * (depth + 1)}{name}")
            if len(files_at[d]) > len(shown):
                lines.append(f"{'  ' * (depth + 1)}... {len(files_at[d]) - len(shown)} more files")

    render("", 0)
    return "\n".join(lines)


def manifest_paths(inv: Inventory) -> list[str]:
    out: list[str] = []
    for f in inv.files:
        p = PurePosixPath(f.path)
        depth = len(p.parts)
        if depth > 3:
            continue
        if p.name in MANIFEST_NAMES or any(fnmatch.fnmatch(p.name, g) for g in MANIFEST_GLOBS):
            out.append(f.path)
        elif (
            p.suffix in {".yml", ".yaml"}
            and any(part.lower() in K8S_DIR_HINTS for part in p.parts[:-1])
        ):
            out.append(f.path)
    return out[:25]


def readme_path(inv: Inventory) -> str | None:
    for f in inv.files:
        if re.fullmatch(r"readme(\.(md|rst|txt|markdown))?", f.path, flags=re.IGNORECASE):
            return f.path
    return None


def entrypoint_paths(inv: Inventory) -> list[str]:
    out: list[str] = []
    for f in inv.files:
        p = PurePosixPath(f.path)
        if len(p.parts) > 3:
            continue
        stem = p.stem.lower()
        if stem in ENTRYPOINT_STEMS and f.language not in {None, "markdown", "json", "yaml", "plaintext"}:
            out.append(f.path)
        elif len(p.parts) >= 2 and p.parts[0] == "cmd" and p.name == "main.go":
            out.append(f.path)
    return out[:15]


def file_block(path: str, body: str, **attrs: str | int) -> str:
    extra = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return f'<file path="{path}"{extra}>\n{body}\n</file>'
