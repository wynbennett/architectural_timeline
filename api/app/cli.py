"""Local CLI: python -m app.cli generate <github_url> [--tags N | --tag NAME]"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from .db import init_db, session_scope
from .ingest.git import parse_github_url
from .llm import generate as gen
from .models import Repo, Tag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="clone a repo and generate graphs")
    g.add_argument("url")
    g.add_argument("--tags", type=int, default=None, help="how many newest tags (default from config)")
    g.add_argument("--tag", default=None, help="generate a single tag by name")
    g.add_argument("--force", action="store_true", help="regenerate even if a graph exists")
    g.add_argument("--tag-pattern", default=None, help=r"regex; only matching tags are eligible (e.g. '^v\d+\.\d+\.\d+$')")

    ls = sub.add_parser("list", help="list repos and tag status")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()

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
