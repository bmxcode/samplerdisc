# ADR-0038 · The container is a runner, not the distribution channel

**Status:** accepted · 2026-09-02

## Context

`samplerdisc` has exactly one untrusted input: a disc image, downloaded from archive.org or a stranger's FTP, whose every offset, length, partition count and sample name is attacker-controlled ([SECURITY.md](../../SECURITY.md)). What the tool does with that input is deliberately narrow — no network, no subprocess, no `eval`, no `pickle`, no dependencies ([ADR-0001](0001-pure-python-stdlib-only.md)), input opened read-only — so the realistic bad outcomes are three: a path escape through `safe_name()` in [src/samplerdisc/extract.py](../../src/samplerdisc/extract.py) writing outside the output directory, resource exhaustion from a crafted image, and a crash.

The question this record settles is whether the project should offer a way to run a batch conversion with those outcomes bounded by the OS rather than only by the tool's own correctness — and, if so, in what form.

A container bounds the first two outcomes cleanly. Mounting the image directory read-only and the output directory as the one writable volume turns a `safe_name()` escape into a scribble on a directory the user already chose; `--network none` makes the no-network claim enforced by the kernel rather than asserted by grepping `src/` for `socket`; `--memory` and `--pids-limit` turn "a crafted image drives unbounded memory" into a container the kernel kills rather than a machine that swaps to death; `--user` lands output owned by the invoking user. What it does **not** buy is protection against code execution, because ADR-0001 already left almost no surface to protect: the residual path is a CPython or zlib memory-safety bug, which is real but unlikely. The tool is not unsafe without the container, and this record and the docs it authorises say so in those words.

## Decision

Ship a `Containerfile` in the repository as a **runner**: a documented, self-contained way to run `samplerdisc batch` against untrusted images with a bounded blast radius. It builds on `python:3.13-slim`, installs the project with `pip install .` (no wheels beyond the project itself, since there are no dependencies), runs as a non-root user, and carries a single documented `docker run` invocation whose every flag is named against the specific [SECURITY.md](../../SECURITY.md) item it addresses. It is **defence in depth, not a fix**, and the "Running images you do not trust" section says as much.

`uv tool install` remains the primary install path. CI builds the image and runs `samplerdisc --version` inside it, in a job kept separate from the required `verify` check, so the recipe cannot silently rot.

**Nothing in the tool changes.** The container was checked for whether it papers over a fixable in-process gap — specifically, whether output paths should be confined under the output directory by a `realpath` assertion. They are already confined: every write is `os.path.join(out_dir, safe_name(...))`, and the only site that splits a name on `/` runs each component through `safe_name()`, whose `rstrip(".")` collapses a `..` or `.` component to `unnamed`. A traversal component cannot survive, so the assertion would be belt-and-suspenders across six write sites rather than a one-line correction, and it is not added. `safe_name()` is the guard; the container bounds a hypothetical bug in it.

## Alternatives rejected

**Publish the image to a registry as a first-class install path.** More convenient — `docker pull` and go — and what a user might expect. Rejected: publishing makes the project a maintained artifact with its own supply chain, base-image CVEs, and rebuild cadence — precisely the thing ADR-0001 congratulates the project for not having, bought for a convenience `uv tool install` already provides without a container at all. A `Containerfile` in the tree has neither the supply chain nor the convenience, and the convenience was never the point: the container earns its place as a security boundary for the batch case, not as a way to install a dependency-free Python tool.

**Fix it in-process instead of documenting a container.** Considered and found to have nothing to fix (see the Decision). Had the output path been unconfined, the container would have been the wrong lever and the fix would have belonged in `extract.py`; it was not, so the container stands as defence in depth over a guard that already holds.

**Say nothing, and let users write their own `docker run`.** Rejected because the useful part is precisely the flag list — which read-only mount, which limit, mapped to which threat — and a line assembled without that mapping tends to drop the flag that mattered. Shipping the invocation with each flag justified is the deliverable; the image is almost incidental.

## Consequences

**Good.** The batch case has a documented, bounded way to run over images off the internet. The no-network and read-only claims become kernel-enforced rather than asserted. The image is built and smoke-tested in CI, so it does not rot. Verified end to end: a batch run over the local `active/` tree produces byte-for-byte identical output inside the container and on the host — same 47 476 samples, same payload digest — so the container demonstrably runs the same tool.

**Bad.** On macOS, Docker Desktop runs a Linux VM and bind-mounts cross a virtiofs boundary, which is slower than native I/O: the same `active/` batch run measured 21 s on the host and 36 s in the container. That cost scales with the bytes crossing the mount, and the image collection is tens of gigabytes. The container is worth it for an image you do not trust and needless for one you rendered yourself.

**Watch for.** The `Containerfile` drifting from a runner toward a distribution channel — a registry push in CI, a `latest` tag users are told to pull, a documented `docker pull` install line. Each is the rejected alternative arriving one commit at a time, and each brings the maintained-artifact supply chain ADR-0001 exists to avoid. The image is how you run an untrusted disc, not how you install the tool.
