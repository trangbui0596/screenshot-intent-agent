# Portfolio Write-Up — Screenshot Intent Agent

## Short version (for project card)

Your screenshots are a graveyard of buried intentions. A LinkedIn profile you meant to reach out to, a company slide you wanted to research, an article you planned to read deeply — all forgotten in your camera roll. Screenshot Intent Agent uses Claude's vision API to analyze every screenshot on your phone, infer *why* you took it, and turn each one into a categorized, actionable to-do in Notion. It pre-filters photos by iPhone screen dimensions to skip selfies and food pics, retries on network failures, resumes interrupted runs, and keeps your Notion page clean with collapsible sections, quick navigation, and a one-command archive workflow that moves completed items out of sight and updates section counts automatically. I built this because I realized my camera roll had become an unprocessed inbox — and no one was reading it.

**Python · Claude Vision API · Notion API · Pillow**

---

## Long version (for project detail page)

### Screenshot Intent Agent

every screenshot is a signal. a linkedin profile means you want to connect with someone. a company presentation means you want to dig deeper. a news article means something resonated and you want to synthesize it into how you think. but screenshots pile up — hundreds of them — and the intent behind each one quietly dies in your camera roll.

i built screenshot intent agent to fix that. it connects to your icloud photos, uses claude's vision api to look at each screenshot, figures out *why* you probably took it, and turns that into a concrete, actionable to-do item in notion — categorized, organized, and ready to act on.

the interesting engineering problem was separating screenshots from regular photos. icloud on windows dumps everything into one flat folder with uuid filenames — no "screenshots" album to filter by. so the agent pre-filters by matching image dimensions against every known iphone screen resolution. out of ~800 photos, it correctly identified 100 screenshots and skipped the rest, saving significant api costs.

the notion output isn't just a flat list. each category (networking, research, synthesis, follow-up, reference) lives in a collapsible toggle section with a table of contents at the top for quick navigation. you check off items as you handle them, then run `--archive` to sweep completed items into a collapsed archive section — and the section counts update automatically so you always know what's left.

it also handles the unglamorous stuff: retry logic with exponential backoff for flaky networks, resume support so a crash at screenshot 76 doesn't mean re-analyzing 75, and batch uploads to work around notion's 100-block api limit.

i built this because i had 3 months of unprocessed intentions sitting in my phone. the agent surfaced 96 actionable items i'd completely forgotten about — people to reach out to, roles to apply for, companies to research. the camera roll went from a graveyard to a pipeline.

**Python · Claude Sonnet 4.6 Vision API · Notion API · Pillow · iCloud Photos**
