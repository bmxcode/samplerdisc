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

## Running images you do not trust

The tool runs with your own privileges on a file you chose to hand it, and that is the right default for a disc you ripped yourself. For a disc image pulled off the internet, the repository ships a `Containerfile` that runs a batch conversion with the three in-scope outcomes above bounded by the OS rather than only by the tool's own correctness. **It is defence in depth, not a fix: the tool is not unsafe without it.** ADR-0001 already left almost no surface here — no network, no subprocess, no `eval`, no `pickle`, no dependencies — so the container is insurance on a narrow set of outcomes, not protection against a code-execution hole there is barely any room for. See [ADR-0038](docs/adr/0038-the-container-is-a-runner-not-the-distribution-channel.md) for the reasoning and the rejected alternative (publishing a maintained image).

Build it once, then run a batch over a directory of images:

```bash
docker build -f Containerfile -t samplerdisc .

docker run --rm \
  --network none \
  --read-only \
  --user "$(id -u):$(id -g)" \
  --memory 2g --pids-limit 256 \
  --mount type=bind,src="$PWD/discs",dst=/discs,ro \
  --mount type=bind,src="$PWD/out",dst=/out \
  samplerdisc batch /discs /out --manifest /out/manifest.json
```

Each flag earns its place against a specific item above — a flag whose purpose cannot be named does not belong in the line:

- **`--network none`** makes the *No network* claim enforced by the kernel rather than asserted by grepping `src/` for `socket`. (Verified: a socket in the container fails with *Network is unreachable*.)
- **`--mount …,ro`** mounts the image directory read-only, so *reading files other than the image you pointed it at* and writing back to an image are refused by the OS, not just by convention.
- **A separate writable `/out`** is the blast radius for *writing outside the output directory*: a `safe_name()` escape scribbles on the output volume you already chose and reaches nothing else.
- **`--read-only`** makes the container's root filesystem immutable, so nothing but `/out` is writable at all. (Verified: a write to `/` fails with *Read-only file system*. Add `--tmpfs /tmp` only if a future run needs scratch space; `batch` does not.)
- **`--user "$(id -u):$(id -g)"`** runs as you, so output files land owned by the invoking user rather than root, and any process that somehow escaped would not be root. The image's default user is unprivileged (`nobody`) when the override is omitted.
- **`--memory` / `--pids-limit`** turn *resource exhaustion out of proportion to the input* into a container the kernel kills rather than a machine that swaps to death. Raise them for a genuinely large collection; the defaults suit the batch case.

What the container does **not** buy is worth stating so the note does not overclaim: it does nothing about a CPython or `zlib` memory-safety bug beyond containing its effect, nothing for the image files themselves, and nothing for anything else on the machine. If the worry is downloaded files in general rather than this tool, the container is the wrong lever.

The container runs the same tool: a batch over the local reference collection produces byte-for-byte identical output on the host and in the container (same sample count, same payload digest). On macOS the bind mount crosses Docker Desktop's Linux VM, which is slower than native I/O — the same run measured 21 s on the host and 36 s in the container — so this is a boundary for untrusted images, not a wrapper to reach for by default. This is a runner, not an install path: `uv tool install` remains that ([ADR-0038](docs/adr/0038-the-container-is-a-runner-not-the-distribution-channel.md)), and no image is published to any registry.

## What happens next

A confirmed report gets a fix on a branch, a pull request with the analysis in its body, and a release. A GitHub security advisory goes out with it, crediting you by name unless you would rather it didn't.
