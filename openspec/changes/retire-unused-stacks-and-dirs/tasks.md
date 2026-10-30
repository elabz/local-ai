## 1. Langfuse decision

- [ ] 1.1 On Prod: `docker ps` for Langfuse containers and their uptime; ask the owner whether the UI is used; record the decision and date in design.md
- [ ] 1.2 If kept: add the `langfuse` callback to `litellm/config.base.yaml`, document `LANGFUSE_*` in `litellm/.env.example`, re-render `config.yaml`, restart LiteLLM, confirm a trace arrives; hand the stack to `pin-floating-container-images`
- [ ] 1.3 If removed: delete `langfuse/`, the `LANGFUSE_*` lines in `litellm/docker-compose.yml` and `config.base.yaml`, README rows and diagram entry; on Prod `compose down` without `-v`

## 2. Tree hygiene

- [ ] 2.1 Remove the `gpu-image-server/models/*.safetensors` ignore rule; annotate `private/` and any other intentionally local-only rule with a `# local-only:` comment
- [ ] 2.2 Confirm with the owner whether local `manuals-parser/` and `gpu-image-server/` are wanted; delete locally if not; either way add annotated ignore rules for both
- [ ] 2.3 `README.md` component table and architecture diagram match the tree; `CLAUDE.md` repository structure likewise

## 3. CI check

- [ ] 3.1 Add `scripts/check-repo-layout.py`: top-level entries vs README table, ignore rules vs `git log --all --name-only`, `--local` mode for untracked directories
- [ ] 3.2 Unit test with a temporary git repository: orphan directory, dead rule, annotated rule, consistent tree
- [ ] 3.3 Run it in `compose-validate`; CI green

## 4. Close out

- [ ] 4.1 If Langfuse was removed: confirmed `docker volume rm` of its volumes on Prod; record here with the date
- [ ] 4.2 `openspec validate --all --strict` passes
