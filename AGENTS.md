# parse

## Git workflow

- This is a local Git repository. Do not create a remote or push unless explicitly requested.
- Automatically commit substantial, coherent changes when complete. Do not commit every minor edit.
- Run relevant local checks at the commit checkpoint, not after every edit. Report any missing test coverage or failed checks honestly.
- Use the user's configured Git author and committer identity. Never add Codex as an author, co-author, or attribution trailer.
- Branch names have no prefix and must not contain `codex`.
- External review tools such as `dt review` require separate explicit authorization.
- Keep credentials, local configuration, dependency directories, and runtime data out of Git.

## Product and implementation

- Build the interface around users uploading guides, reviewing rules and changes, and validating scenarios. Keep development tracking out of the product interface.
- Follow `docs/build-spec.md` for the architecture and preserve original evidence and full document coverage.
- When adding code to a ShipHero repository, consult the methodology and best-practice documentation in the Shiphero-API repository or https://docs.shiphero.com/.
