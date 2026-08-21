# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | ✅ |
| ≤ 0.2.x | ❌ |

Fixes land on `main` and go out in the next release. This is a single-maintainer project, so there is no backport branch — upgrading to the current release is the upgrade path.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on [the repository](https://github.com/bmxcode/samplerdisc/security). Please don't open a public issue for something exploitable.

Expect an acknowledgement within about a week. That is a realistic figure for a hobby project with one maintainer and no on-call, not a service level agreement.

Include the exact command you ran, the container and filesystem involved, the output of `samplerdisc --version`, and what happened. **Never attach a disc image or extracted audio** — the same rule as ordinary bug reports ([ADR-0008](docs/adr/0008-no-media-in-the-repo.md)). A minimal crafted image that reproduces the problem is more useful than a commercial library anyway, and it is the one kind of image that may be attached.

## What the threat model actually is

`samplerdisc` has exactly one untrusted input: a disc image, usually downloaded from archive.org or a stranger's FTP and named by whoever uploaded it. Every offset, length, partition count and sample name inside that image is attacker-controlled, and the parsers are the security surface of this project.

What the tool does with it is narrow, and worth stating because it bounds what a bad image can reach:

- **No network.** Nothing in `src/` imports `socket`, `urllib`, `http` or anything like them. The tool never opens a connection.
- **No subprocess, no `eval`, no `pickle`, no shell.** Nothing is deserialised and nothing is executed.
- **No dependencies.** The whole tool is the CPython standard library ([ADR-0001](docs/adr/0001-pure-python-stdlib-only.md)), so there is no third-party supply chain to compromise.
- **Input images are opened read-only.** The tool writes to the output directory you name, and nowhere else.

### In scope — please report these privately

- **Writing outside the output directory.** Volume and sample names come off the disc and become filenames, so they pass through an allowlist first: `safe_name()` in [src/samplerdisc/extract.py](src/samplerdisc/extract.py) replaces everything outside `[A-Za-z0-9 ._+#-]`, which means `/`, `\` and `:` cannot survive it, and a dot-only name becomes `unnamed`. A name that escapes the output directory regardless is a vulnerability.
- **Code or command execution** triggered by image content.
- **Reading files other than the image you pointed it at.**
- **Resource exhaustion out of proportion to the input** — a small image that drives unbounded memory or unbounded output. Compressed `.mdx` is inflated in bounded blocks rather than in one call, so a compression bomb should not be possible; a case where it is, counts.

### Out of scope — open a normal issue instead

- **A crash or traceback on a damaged image.** This is a real bug and worth reporting — the project rule is that damaged input degrades and never crashes — but it is not a security boundary. The tool runs with your own privileges, on a file you chose to hand it.
- **A disc that won't read, wrong audio, or a wrong sample rate.** Those are format problems; the issue templates cover them.
- **Memory or disk use proportional to a genuinely large disc.**

Use the [issue templates](https://github.com/bmxcode/samplerdisc/issues/new/choose) for anything in this second list. `samplerdisc info` output is the useful thing to paste.

## What happens next

A confirmed report gets a fix on a branch, a pull request with the analysis in its body, and a release. A GitHub security advisory goes out with it, crediting you by name unless you would rather it didn't.
