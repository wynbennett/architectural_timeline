"""Local CLI: python -m app.cli generate <github_url> [--tags N | --tag NAME]"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from .db import init_db, session_scope
from .ingest.git import parse_github_url
from .llm import jobs as gen
from .models import Graph, Repo, Tag


def _redact(url: str) -> str:
    """Hide credentials when echoing a database URL."""
    import re

    return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="clone a repo and generate graphs")
    g.add_argument("url")
    g.add_argument("--tags", type=lambda v: max(1, int(v)), default=None, help="how many newest tags (default from config)")
    g.add_argument("--tag", default=None, help="generate a single tag by name")
    g.add_argument("--force", action="store_true", help="regenerate even if a graph exists")
    g.add_argument("--tag-pattern", default=None, help=r"regex; only matching tags are eligible (e.g. '^v\d+\.\d+\.\d+$')")

    ls = sub.add_parser("list", help="list repos and tag status")

    rh = sub.add_parser("rehash", help="fill in blob hashes for inventories generated before hashing existed (needs the local clone)")

    mg = sub.add_parser("migrate", help="create/upgrade the schema on a database (safe to re-run)")
    mg.add_argument("--db", default=None, help="database URL (default: DATABASE_URL)")

    sy = sub.add_parser("sync-to", help="copy repos, tags, graphs, inventories and summaries to another database")
    sy.add_argument("target", help="target database URL, e.g. postgres://...")
    sy.add_argument("--from", dest="source", default=None, help="source database URL (default: DATABASE_URL)")
    sy.add_argument("--repo", default=None, help="only this repo, as owner/name")
    sy.add_argument("--graphs-only", action="store_true", help="skip tags that have no graph")
    sy.add_argument("--dry-run", action="store_true", help="report what would be copied")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "migrate":
        from .config import Config
        from .db import make_engine

        url = args.db or Config.DATABASE_URL
        engine = make_engine(url)
        init_db(engine)
        from sqlalchemy import inspect

        print(f"schema ready on {_redact(url)}: tables={sorted(inspect(engine).get_table_names())}")
        return 0

    if args.cmd == "sync-to":
        from .config import Config
        from .sync import sync

        source = args.source or Config.DATABASE_URL
        report = sync(source, args.target, repo_filter=args.repo, dry_run=args.dry_run, graphs_only=args.graphs_only)
        print(("dry run: " if args.dry_run else "synced: ") + str(report) + f"  ->  {_redact(args.target)}")
        for item in report.skipped:
            print("  skipped", item)
        return 0

    init_db()

    if args.cmd == "rehash":
        from .ingest.workspace import open_workspace
        from .models import File

        with session_scope() as s:
            for t in s.scalars(select(Tag).join(Graph, Graph.tag_id == Tag.id)).all():
                rows = [f for f in t.files if not f.blob_sha]
                if not rows:
                    continue
                shas = {p: sha for p, _, sha in open_workspace(t.repo.owner, t.repo.name, t.commit_sha).list_files()}
                n = 0
                for f in rows:
                    if shas.get(f.path):
                        f.blob_sha, n = shas[f.path], n + 1
                print(f"{t.repo.name}@{t.name}: hashed {n} of {len(rows)} files")
        return 0

    if args.cmd == "list":
        with session_scope() as s:
            for r in s.scalars(select(Repo)).all():
                print(f"[{r.id}] {r.url}")
                for t in r.tags:
                    mark = "●" if t.graph else "○"
                    print(f"    {mark} {t.name:20s} {t.status:8s} {t.error or ''}")
        return 0

    owner, name = parse_github_url(args.url)
    canonical = f"https://github.com/{owner}/{name}"
    with session_scope() as s:
        repo = s.scalar(select(Repo).where(Repo.url == canonical))
        if repo is None:
            repo = Repo(url=canonical, owner=owner, name=name)
            s.add(repo)
            s.flush()
        repo_id = repo.id

    gen.load_repo(repo_id)
    if args.tag:
        with session_scope() as s:
            tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == args.tag))
            if tag is None:
                print(f"tag {args.tag} not found", file=sys.stderr)
                return 1
            tag_id = tag.id
        gen.generate_tag(repo_id, tag_id, force=args.force)
    else:
        gen.generate_newest(repo_id, n=args.tags, force=args.force, tag_pattern=args.tag_pattern)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
