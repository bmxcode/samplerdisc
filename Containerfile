# Containerfile -- a runner for untrusted disc images, not a distribution channel.
#
# The images samplerdisc reads come off archive.org or a stranger's FTP, and
# every byte inside one is attacker-controlled (SECURITY.md). This image lets a
# batch run happen with a bounded blast radius. It is defence in depth, not a
# fix: the tool is not unsafe without it. See ADR-0038 and the "Running images
# you do not trust" section of SECURITY.md for the invocation and what each of
# its flags does and does not buy.
#
# It is a recipe in the tree, deliberately not a published image: ADR-0001 keeps
# this project free of a maintained artifact with its own supply chain, and
# `uv tool install` stays the primary install path.

FROM python:3.13-slim

# No build step and no wheels beyond the project itself -- ADR-0001 means there
# are no dependencies to resolve. README.md is the project's `readme`, so the
# build needs it; LICENSE rides along for provenance.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /src
WORKDIR /

# Run as an unprivileged user by default. The documented invocation overrides
# this with --user "$(id -u):$(id -g)" so output files land owned by the
# invoking user rather than root; running as nobody is the safe fallback when it
# does not.
USER 65534:65534

ENTRYPOINT ["samplerdisc"]
