# Project skills — profile & publication design

Skills in this folder load automatically for Claude Code sessions on this repository.

| Skill | Purpose | Source | License |
|---|---|---|---|
| `saudi-contractor-profile` | Evidence-grounded Arabic RTL company profiles for Saudi contractors (PPTX/PDF) | Provided by the repository owner | Owner-provided |
| `canvas-design` | Poster / page-level visual composition (PNG/PDF) with bundled display fonts | [anthropics/skills](https://github.com/anthropics/skills) `skills/canvas-design` | Apache-2.0 (`LICENSE.txt`); fonts SIL OFL 1.1 |
| `theme-factory` | Ready colour/font themes for decks, documents and reports | [anthropics/skills](https://github.com/anthropics/skills) `skills/theme-factory` | Apache-2.0 (`LICENSE.txt`) |
| `frontend-design` | HTML/CSS editorial layouts (web magazines, digital brochures, landing pages) | [anthropics/skills](https://github.com/anthropics/skills) `skills/frontend-design` | Apache-2.0 (`LICENSE.txt`) |

The three Anthropic skills are copied unchanged from `anthropics/skills` at commit
`dbd4588f9e1033efb41dad4bef2f7947c8993d44`, together with their `LICENSE.txt` files.
`canvas-design/canvas-fonts` ships an `*-OFL.txt` per font family. The IBM Plex Serif and
Instrument Serif files are covered by the same SIL OFL 1.1 as their sibling families
(IBM Plex Mono and Instrument Sans) upstream.

## Not copied here

- `pptx`, `pdf`, `docx`, `xlsx` (the `document-skills` plugin) are under a proprietary Anthropic
  license that forbids copying them outside Anthropic's services. They are referenced instead
  through the `anthropic-agent-skills` marketplace in `.claude/settings.json`. If they do not
  load automatically, run:
  `/plugin marketplace add anthropics/skills` then `/plugin install document-skills@anthropic-agent-skills`.
- `doc-coauthoring` and `skill-creator` come with the `example-skills` plugin
  (`/plugin install example-skills@anthropic-agent-skills`). `doc-coauthoring` has no license file,
  so it is not vendored.
- `brand-guidelines` applies Anthropic's own brand; it is intentionally excluded.
