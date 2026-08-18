# ADR-0010 · Build the instrument layer ourselves rather than handing off

**Status:** accepted · 2026-08-18

## Context

[ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) turned out to overlap this project more than was understood when it was planned. It is a mature, actively maintained LGPL-3.0 Java multisample converter, and as of its March 2026 vintage-Akai update it reads **Akai S1000/S3000 ISO images directly**, along with `.S3P` programs and MPC keygroups. It writes SFZ, DecentSampler, Bitwig, MPC/Force, EXS, SF2 and more — a destination list this project will not approach.

What it does not read is containers. No compressed `.mdx`, no `.nrg`, no raw `.bin`/`.cue`. Users hit exactly that wall: a reviewer of the archive.org collection advises running `bin2iso` first so ConvertWithMoss can see the disc, which works for `.bin` and does nothing for the `.mdx` and `.nrg` files in the same collection.

So the layers divide cleanly: containers are ours alone, the AKAI filesystem is shared, and the instrument layer — programs, keygroups, velocity layers, mapping to SFZ and friends — is theirs and better.

## Decision

Build the full stack anyway, including program and keygroup conversion. `samplerdisc` takes a disc from any supported container all the way to usable instruments without a second tool.

## Alternatives rejected

**Position as a container front-end and hand instruments off to ConvertWithMoss.** Strictly less duplicated work, and each tool would do what it is best at: `export-iso` already produces exactly the input ConvertWithMoss wants, so the integration is free and the README could simply document the handoff. Rejected on the user experience of the actual job. Someone converting a shelf of discs should not have to chain two tools with different conventions, install a JRE, and reconcile two output layouts — and the batch and manifest work only pays off if one process owns the whole pipeline.

**Narrow to containers only and drop WAV extraction as well.** The sharpest possible tool. Rejected for the same reason, more so.

## Consequences

**Good.** One install, one CLI, one output layout, no Java runtime. Batch conversion and the manifest cover the whole pipeline rather than half of it.

**Bad.** Real duplication of a mature project, and the AKAI program format becomes ours to track. Our instrument output will start worse than ConvertWithMoss's and may stay worse.

**Watch for.** Scope creep into being a general multisample converter. The destination-format list is precisely where ConvertWithMoss wins, and chasing it is unwinnable. Extracting instruments from discs is the job; becoming a format hub is not.

**Regardless of this decision,** `export-iso` stays first class ([ADR-0009](0009-export-iso-escape-hatch.md)). It is what makes ConvertWithMoss usable on a `.mdx`, and that is worth offering whether or not we duplicate what comes after.
