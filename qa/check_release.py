"""Read-only release audit for an ITR candidate, local ZIP, and optional Git history."""
import argparse
import hashlib
import io
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

IDENTITY = ("ITR Release", "itr@invalid.example")
LEGACY = "docs/history-0.1/MANIFEST.sha256"
LEGACY_SHA256 = "32f4668fd18b403d82080878c049eeec27b9d0e2670c11181a74791cadff4733"
MAX_SIZE = 32 * 1024 * 1024
CORE = {"SKILL.md", "README.md", "README.en.md", "VERSION", LEGACY, "qa/check_release.py"}
FILES = set("""
.gitignore VERSION README.md README.en.md SKILL.md VERIFICATION.ko.md MANIFEST.sha256
docs/architecture.ko.md docs/assessment.ko.md docs/gates.ko.md docs/release.ko.md
docs/history-0.1/VERIFICATION.ko.md docs/history-0.1/MANIFEST.sha256
examples/preview/replay.html examples/preview/print.html examples/preview/report.md examples/preview/report.pdf
qa/check_views.py qa/check_replay.cjs qa/check_browser.py qa/check_release.py qa/package-checks.json qa/print_pdf.py
schemas/README.md schemas/record.schema.json schemas/project-plan.schema.json schemas/validate.py
tools/check_itr.py tools/itr.py tools/itr_store.py tools/itr_fixture.py tools/sample_receipt.py tools/progress.py
views/render.py views/replay.template.html views/progress.html
""".split())
NEW_FILES = set("""
tools/project.py tools/project_plan.py tools/project_process.py tools/project_verify.py
qa/check_project.py qa/check_progress.py qa/browser-check.rc1.json qa/project-check.rc1.json qa/pdf-pagination.rc1.json
qa/check_progress_dom.cjs qa/dom_test_double.cjs qa/progress-dom.rc1.json qa/progress-watcher.rc1.json
examples/project/checks.py examples/project/inventory.py examples/project/plan-defect.json examples/project/plan.json examples/itr-selfcheck.json
""".split())
REVIEWED = {
    LEGACY: LEGACY_SHA256,
    "examples/project/checks.py": "c1dec4f971b7a63194294344da2d8d28884a3e60683a36ca9640165da9f73a8a",
    "examples/project/inventory.py": "d70dd95ea16a575a71a198ae5ceac507710d7776846104172b3c401d0c2ce0e1",
    "examples/project/plan.json": "89fcc130dbe6a142c9f3d52f13ec71a78cfb74b28c9302c97ef919f516a08c24",
    "examples/project/plan-defect.json": "ec3f7b6e48a30ec6a1d8da61f4520329bdc85348863bf9c00e0cfa77367b37e1",
}
PROJECT_RECORDS = {
    "round-0001/attempt-0001": {
        "COMPLETE.json": "15e088a9eb61aa2666b36e03318732b4a3b85bbb896afb9ad32ec24e843f3682",
        "approval.json": "294d4ae7e328b9f88485d7b8abbb40798c4a4ab9f3d52b2c76f852db3344db65",
        "events/0001.json": "f18759b19a301a762de452416253fa0cb8c4436a2a1475811c47f00f92770c26",
        "events/0002.json": "4ece0bc17be6f82c678d1714e0fedcf3ea42d9b2e4799cf9a60d8a3d07f29c4d",
        "events/0003.json": "fd104455956b3a19d5f92168408eec238fdb19fdf23ad16bde9404a25cfaf051",
        "events/0004.json": "210108fd60ed882527e871cd772f7c586b874f1949a2307cd37ef6c0a7cf71d4",
        "events/0005.json": "7a831ab9557c83df93b2882b0656dd540c798eb49b70b9992294b80722a02bcc",
        "events/0006.json": "9f56346275a6c82eb40497a5fd5e51db63d25426f802df434ebc800436a9bbfc",
        "evidence/0001.json": "a2d0fffc0dfc77d74f14095a288a064bbedf7d3b8dddadd8b094ebffcef49b36",
        "evidence/0002.json": "577196abe40599c5bb40334085c16105db25793c0411171ad7415472c100f30b",
        "input.json": "9881dd075edddbefd13f7001787cf33000815d480f724e3cec60a0a9a59baf25",
        "plan.json": "89fcc130dbe6a142c9f3d52f13ec71a78cfb74b28c9302c97ef919f516a08c24",
        "record.json": "6da0409da8e063b707ca679f982cbda1769594cdbcd772145951366b92224213",
        "reservation.json": "e8423704119837180222361a2c5cd2d26fb92adae3816927ecf77212a6e646e2",
        "sources/checks.py": "c1dec4f971b7a63194294344da2d8d28884a3e60683a36ca9640165da9f73a8a",
        "sources/inventory.py": "d70dd95ea16a575a71a198ae5ceac507710d7776846104172b3c401d0c2ce0e1"
    },
    "round-0002/attempt-0001": {
        "COMPLETE.json": "e00149f142fcb11674351704e0d82665ae993051cb12280378596dfbf197cb99",
        "approval.json": "1effddbd6280ebf5611e078dcbe615a21901483c4b1c731db2b13fbdc93bcae9",
        "events/0001.json": "7d99d6fbadb674516ddbd210b710bc0fa53fda90660896d11e90dcf045bea5cb",
        "events/0002.json": "178c1cc34308db80975d1d06f7c811b487ea2c813413dc9f32bbd0081167a79b",
        "events/0003.json": "b5b99cd1822ba45aac1a72e0746995689ecbd8ab92ead9417463fd4fc52dcee9",
        "events/0004.json": "15c4e9c1d25f6d24861276bb0dc270c916482b62136cdac0fc17e78dbd8f8f6b",
        "events/0005.json": "0398b832effe9e7ba4662c05391b4ab1ac83765b0a13491c787d0f7d4f6a5014",
        "events/0006.json": "b34c1429dbe0057e342867b84c1ed1cc6d1df01ddfa5220908836abacceeb7f4",
        "events/0007.json": "2b0b16a7fd2fbe8a45ec3f1f03f4d84ede0036defd194020855e91253bb33832",
        "events/0008.json": "1b54b72255dc55143f65c0bb22c47fd23c354bec7c600f495833ce95077012eb",
        "events/0009.json": "4171b21d12dbb2a26fa4c8693b1782cdc8d4b824d780d13058efc8d8333e1776",
        "evidence/0001.json": "4ce5b89473e4ebfdf9e2cfae7bfc5438e51ac5f6ba1122edd6942bc6edafb94e",
        "evidence/0002.json": "72ca4da568b1cebdd10ce5907a52d272fc41e3bc6e9211068b4f4da6b78710b3",
        "evidence/0003.json": "2af36d44424d24a34ec14f8179b5b53b81a293f9f579bb2f4b2b992513125aed",
        "input.json": "c8bbc6c6f850a2a74eb9413249c3b197d0005bba0cdadf5279d5b4069c99f1df",
        "plan.json": "ec3f7b6e48a30ec6a1d8da61f4520329bdc85348863bf9c00e0cfa77367b37e1",
        "record.json": "452bcd9c3e0eee97610c23684928e4edada9af30f2e7e870953873be8ee0208b",
        "reservation.json": "a115ad790fa1c57cfa74ee3ac42395f3d90ec67253709950933c76061579ea39",
        "sources/checks.py": "c1dec4f971b7a63194294344da2d8d28884a3e60683a36ca9640165da9f73a8a",
        "sources/inventory.py": "d70dd95ea16a575a71a198ae5ceac507710d7776846104172b3c401d0c2ce0e1"
    }
}
DOMAINS = {"www.iso.org", "www.w3.org", "json-schema.org", "github.com",
           "docs.github.com", "cli.github.com", "git-scm.com"}
EMAIL = re.compile(r"(?i)[a-z0-9.!#$%&*+/=?^_~-]+@[a-z0-9.-]+\.[a-z]{2,}")
URL_HOST = re.compile(r"(?i)\bhttps?://([^/?#\s<>\"'()]+)")
RULES = {
    "credential": r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{30,}|xox[abpors]-[A-Za-z0-9-]{14,}|(?:AKIA|ASIA)[0-9A-Z]{16}|sk-(?:proj-|live_|test_)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY-----|Authorization\s*:\s*Bearer\s+[a-z0-9._~+/-]{12,})",
    "credential-assignment": r"""(?ix)\b(?:access[_-]?token|api[_-]?key|client[_-]?secret|password)\b["']?\s*[:=]\s*["']?[a-z0-9._~+/-]{12,}""",
    "contact": r"(?<![\w-])(?:\+?82[- .]?0?1[016789][- .]?\d{3,4}[- .]?\d{4}|01[016789][- .]?\d{3,4}[- .]?\d{4}|0(?:2|[3-6][1-5])[- .]\d{3,4}[- .]\d{4}|\+1[- .]?\(?\d{3}\)?[- .]?\d{3}[- .]?\d{4}|\(\d{3}\) ?\d{3}[- ]\d{4})(?![\w-])",
    "identity-number": r"(?<![\w-])\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-[1-8]\d{6}(?![\w-])",
    "private-path": r"""(?i)(?:/(?:home|Users|workspace|root|mnt/data|private/var|var/folders|tmp)/(?:[^/\s"'<>]+)|[a-z]:[/\\]+(?:Users|Documents and Settings)[/\\]|file:[/]{3}(?![/\s"'<>]))""",
    "customer-field": r"""(?ix)["'](?:customer[_-]?(?:email|phone|address|name)|social[_-]?security|주민등록번호|고객전화번호)["']\s*:\s*["'][^"'<>]{3,}""",
}
RULES = {name: re.compile(pattern) for name, pattern in RULES.items()}


class AuditError(ValueError):
    pass


def require(test, label):
    if not test:
        raise AuditError(label)


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def run(argv, data=None):
    try:
        result = subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise AuditError("required local tool missing or timed out") from None
    require(result.returncode == 0, "local inspection command failed")
    return result.stdout


class Audit:
    def __init__(self, root, terms):
        self.root = root
        self.terms = terms
        self.hashes = {}
        self.scanned = set()
        source = (root / LEGACY)
        require(source.is_file() and not source.is_symlink(), "legacy manifest missing")
        raw = source.read_bytes()
        require(hash_bytes(raw) == LEGACY_SHA256, "legacy provenance mismatch")
        self.original = {}
        for line in raw.decode("utf-8").splitlines():
            checksum, path = line.split("  ", 1)
            if path.startswith("examples/runs/"):
                self.original[path] = checksum
        for folder, members in PROJECT_RECORDS.items():
            for name, checksum in members.items():
                self.original[f"examples/project-runs/{folder}/{name}"] = checksum

    def location(self, name):
        # Unknown filenames themselves can contain personal information.
        return name if name in FILES or name in NEW_FILES or name in self.original else "[unlisted path]"

    def allowed(self, name):
        return name in FILES or name in NEW_FILES or name in self.original

    def text(self, value, where):
        for name, regex in RULES.items():
            match = regex.search(value)
            if match:
                line = value[:match.start()].count("\n") + 1
                raise AuditError(f"{name} · {where} · line {line}")
        for found in EMAIL.finditer(value):
            require(found.group().lower() == IDENTITY[1], "email · " + where)
        # Local loopback servers are part of the explicitly local progress demo.
        for match in URL_HOST.finditer(value):
            host = match.group(1).lower()
            local = re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", host)
            require(local or host in DOMAINS, "unreviewed URL host · " + where)
        lower = value.casefold()
        require(not any(t in lower for t in self.terms), "operator-supplied private term · " + where)

    def data(self, name, content):
        where = self.location(name)
        require(self.allowed(name), "path outside allowlist · " + where)
        require(len(content) <= MAX_SIZE, "size limit · " + where)
        checksum = hash_bytes(content)
        if name in REVIEWED:
            require(checksum == REVIEWED[name], "reviewed sample or manifest changed · " + where)
        if name in self.original:
            require(checksum == self.original[name], "pinned synthetic sample changed · " + where)
        key = (name.rsplit(".", 1)[-1], checksum)
        if key in self.scanned:
            return checksum
        if name.endswith(".pdf"):
            meta = run(["pdfinfo", "-"], content).decode("utf-8")
            self.text(meta, "PDF properties")
            self.text(run(["pdfinfo", "-meta", "-"], content).decode("utf-8"), "PDF XMP")
            text = run(["pdftotext", "-layout", "-", "-"], content).decode("utf-8")
            require(text.strip(), "PDF has no extractable text")
            self.text(text, "PDF text")
            creator = re.search(r"(?m)^Author:\s*(.*?)\s*$", meta)
            require(not creator or creator.group(1) == IDENTITY[0], "PDF author")
            require(re.search(r"(?m)^JavaScript:\s*no\s*$", meta), "PDF active content")
            with tempfile.TemporaryDirectory(prefix="itr-pdf-") as temp:
                document = Path(temp) / "report.pdf"
                document.write_bytes(content)
                require(run(["pdfdetach", "-list", str(document)]).strip() == b"0 embedded files",
                        "PDF attachment")
        else:
            require(b"\0" not in content, "unexpected binary · " + where)
            try:
                value = content.decode("utf-8")
            except UnicodeDecodeError:
                raise AuditError("non-UTF-8 text · " + where) from None
            self.text(value, where)
        self.scanned.add(key)
        return checksum

    def tree(self):
        directories = {parent.as_posix() for name in FILES | NEW_FILES | set(self.original)
                       for parent in Path(name).parents}
        directories.update(f"examples/project-runs/{folder}/reviews" for folder in PROJECT_RECORDS)
        for parent, dirs, files in os.walk(self.root, followlinks=False):
            base = Path(parent)
            for child in list(dirs):
                if base == self.root and child == ".git":
                    require(not (base / child).is_symlink(), "unexpected git directory link")
                    dirs.remove(child)
                    continue
                require((base / child).relative_to(self.root).as_posix() in directories, "unlisted source directory")
                require(not (base / child).is_symlink(), "unexpected directory link")
            for child in files:
                p = base / child
                rel = p.relative_to(self.root).as_posix()
                require(self.allowed(rel), "path outside allowlist · " + self.location(rel))
                info = p.lstat()
                require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_SIZE, "non-regular or oversized file")
                self.hashes[rel] = self.data(rel, p.read_bytes())
        require(CORE <= set(self.hashes), "mandatory release source missing")
        require(set(self.original) <= set(self.hashes), "pinned synthetic sample missing")

    def complete(self):
        require(FILES | NEW_FILES <= self.hashes.keys(), "release component missing")
        manifest = {}
        for row in (self.root / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            checksum, name = row.split("  ", 1)
            require(name not in manifest and re.fullmatch(r"[0-9a-f]{64}", checksum),
                    "invalid release manifest entry")
            manifest[name] = checksum
        expected = {name: checksum for name, checksum in self.hashes.items() if name != "MANIFEST.sha256"}
        require(manifest == expected, "release manifest content or inventory differs")

    def archive(self, package):
        names = set()
        require(package.stat().st_size <= 128 * 1024 * 1024, "ZIP container size")
        with zipfile.ZipFile(package) as archive, package.open("rb") as raw:
            raw.seek(-22, 2)
            end = raw.read(22)
            sig, disk, start_disk, count_disk, count, central_size, central_at, comment_len = struct.unpack("<4s4H2LH", end)
            require(sig == b"PK\x05\x06" and not (disk or start_disk or comment_len) and count_disk == count,
                    "ZIP end record")
            require(central_at + central_size == raw.tell() - 22, "ZIP trailing or hidden data")
            expected_offset = 0
            for entry in sorted(archive.infolist(), key=lambda e: e.header_offset):
                require(entry.header_offset == expected_offset, "ZIP hidden data between members")
                raw.seek(entry.header_offset)
                header = raw.read(30)
                require(len(header) == 30 and header[:4] == b"PK\x03\x04", "ZIP local header")
                name_len, extra_len = struct.unpack_from("<HH", header, 26)
                require(extra_len == 0 and not (entry.flag_bits & 8), "ZIP local extra data")
                expected_offset = entry.header_offset + 30 + name_len + entry.compress_size
            require(expected_offset == central_at, "ZIP unexpected member data")
            require(not archive.comment, "ZIP comment")
            members = archive.infolist()
            require(0 < len(members) <= 8192, "ZIP entry count")
            filenames = [m.filename for m in members if not m.is_dir()]
            roots = {n.split("/", 1)[0] for n in filenames}
            prefix = ""
            if len(roots) == 1 and not (set(filenames) & self.hashes.keys()):
                label = next(iter(roots))
                require(re.fullmatch(r"ITR(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?", label), "ZIP root")
                prefix = label + "/"
            require(len({m.filename for m in members}) == len(members), "duplicate ZIP path")
            allowed_dirs = {prefix}
            allowed_dirs.update(prefix + f"examples/project-runs/{folder}/reviews/" for folder in PROJECT_RECORDS)
            for rel in self.hashes:
                parts = rel.split("/")
                allowed_dirs.update(prefix + "/".join(parts[:i]) + "/" for i in range(1, len(parts)))
            for m in members:
                require(not m.comment and not m.extra and not (m.flag_bits & 1), "ZIP entry metadata")
                if m.is_dir():
                    require(m.filename in allowed_dirs, "unlisted ZIP directory")
                    continue
                require(m.filename.startswith(prefix), "ZIP prefix mismatch")
                rel = m.filename[len(prefix):]
                require(rel in self.hashes, "unlisted ZIP member")
                mode = stat.S_IFMT(m.external_attr >> 16)
                require(mode in (0, stat.S_IFREG) and m.file_size <= MAX_SIZE, "ZIP file type or size")
                require(hash_bytes(archive.read(m)) == self.hashes[rel], "ZIP bytes differ · " + self.location(rel))
                names.add(rel)
        require(names == self.hashes.keys(), "ZIP inventory differs")

    def git(self):
        git = ["git", "--no-replace-objects", "-C", str(self.root)]
        require((self.root / ".git").is_dir(), "candidate is not a standalone Git root")
        require(Path(os.fsdecode(run(git + ["rev-parse", "--show-toplevel"]).strip())).resolve() == self.root, "Git root mismatch")
        require(not run(git + ["status", "--porcelain=v1", "-z", "--untracked-files=all"]), "dirty Git tree")
        require(run(git + ["rev-parse", "--is-shallow-repository"]).strip() == b"false", "shallow Git history")
        refs = run(git + ["for-each-ref", "--format=%(refname)"]).decode("utf-8").splitlines()
        require(set(refs) <= {"refs/heads/main", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"},
                "unexpected ref in initial release repository")
        commits = run(git + ["rev-list", "--all", "HEAD"]).decode("ascii").splitlines()
        require(commits, "empty Git history")
        seen_blobs = set()
        head = run(git + ["rev-parse", "HEAD"]).decode().strip()
        for commit in commits:
            raw = run(git + ["cat-file", "commit", commit]).decode("utf-8")
            header, message = raw.split("\n\n", 1)
            for kind in ("author", "committer"):
                match = re.search(r"(?m)^" + kind + r" (.+?) <([^>]+)> \d+ [+-]\d{4}$", header)
                require(match and match.groups() == IDENTITY, "unauthorized Git " + kind)
            self.text(header + "\n" + message, "Git commit")
            entries = run(git + ["ls-tree", "-rz", "--full-tree", commit]).split(b"\0")
            tracked = set()
            for row in filter(None, entries):
                meta, raw_name = row.split(b"\t", 1)
                mode, kind, oid = meta.decode("ascii").split()
                name = raw_name.decode("utf-8")
                require(mode in ("100644", "100755") and kind == "blob" and self.allowed(name),
                        "unlisted file or special object in Git history · " + self.location(name))
                tracked.add(name)
                key = (name, oid)
                if key not in seen_blobs or commit == head:
                    size = int(run(git + ["cat-file", "-s", oid]).strip())
                    require(size <= MAX_SIZE, "oversized Git object")
                    checksum = self.data(name, run(git + ["cat-file", "blob", oid]))
                    if commit == head:
                        require(checksum == self.hashes.get(name), "HEAD differs from audited tree")
                    seen_blobs.add(key)
            if commit == head:
                require(tracked == self.hashes.keys(), "HEAD inventory differs")
        return len(commits)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, default=Path("."))
    cli.add_argument("--zip", type=Path, help="Verify every member against the audited local tree")
    cli.add_argument("--git", action="store_true", help="Inspect local reachable history and HEAD")
    cli.add_argument("--private-terms", type=Path, help="Optional external UTF-8 list, one sensitive term per line")
    args = cli.parse_args()
    root = args.root.resolve()
    terms = []
    if args.private_terms:
        path = args.private_terms.resolve()
        require(root not in path.parents and path != root, "private term list must be outside release")
        terms = [t.strip().casefold() for t in path.read_text(encoding="utf-8").splitlines() if t.strip()]
    audit = Audit(root, terms)
    audit.tree()
    if args.zip or args.git:
        audit.complete()
    if args.zip:
        audit.archive(args.zip)
    count = audit.git() if args.git else 0
    print(f"PASS · source files {len(audit.hashes)} · ZIP {'checked' if args.zip else 'skipped'} · Git commits {count}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditError as err:
        sys.exit("FAIL · " + str(err))
    except (ValueError, OSError, UnicodeError, zipfile.BadZipFile, RuntimeError):
        sys.exit("FAIL · malformed or unreadable release input")
