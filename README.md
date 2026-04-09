# Screenshot Intent Agent

An AI agent that analyzes your iPhone screenshots, infers *why* you took each one, and creates a categorized to-do list in Notion.

**The insight:** Every screenshot is an implicit intention. A LinkedIn profile means you want to connect. A company slide means you want to research. An article means you want to synthesize. This agent surfaces those buried intentions and turns them into actions.

## How It Works

```
iPhone Screenshots  →  Pre-filter  →  Claude Vision  →  Notion To-Do Page
     (iCloud)        (dimensions)     (intent analysis)   (categorized)
```

1. **Scan** — Reads your iCloud Photos folder and filters to screenshots using iPhone screen dimension matching (skips regular photos)
2. **Analyze** — Sends each screenshot to Claude's vision API to infer intent and extract actionable details
3. **Categorize** — Groups results into 6 categories:
   - **Networking** — People to reach out to
   - **Research** — Topics/companies to explore
   - **Synthesis** — Ideas to integrate into your thinking
   - **Follow-up** — Items requiring action (applications, bookings, etc.)
   - **Reference** — Material to save for later
   - **Other** — Miscellaneous actionable items
4. **Push to Notion** — Creates a structured page with collapsible sections, a navigation bar, and checkable to-do items
5. **Archive** — Check off completed items in Notion, then run `--archive` to move them to a collapsible Archive section (section counts update automatically)

## Example Output

The agent creates a Notion page with a table of contents for quick navigation and collapsible toggle sections:

```
📱 Screenshot Actions — 2026-04-09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📑 Table of Contents
  Networking · Research · Synthesis · Follow Up · Reference

▶ 🤝 Networking (12)                          ← click to expand
  ☐ Connect with Sarah Chen — VP Engineering at Anthropic
    Action: Send LinkedIn message referencing her recent post on ML ops
    Details: Sarah Chen, VP Engineering, 15+ years experience...

▶ 🔬 Research (8)
  ☐ Deep dive into Stripe's new billing architecture
    Action: Read the full presentation and compare to current stack

▶ 💡 Synthesis (4)
  ☐ Integrate "build in public" framework into content strategy
    Action: Extract the 3 core principles from this article and...

▶ 📌 Follow Up (15)
  ☐ Apply for Growth role at Julius AI
    Action: Submit application before deadline...

▶ 🗄️ Archive                                  ← collapsed by default
  ☑ (completed items get moved here)
```

## Setup

### Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)
- A [Notion integration token](https://www.notion.so/my-integrations)
- iPhone screenshots synced via iCloud Photos (or any local folder)

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/screenshot-intent-agent.git
cd screenshot-intent-agent
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `NOTION_TOKEN` | Your Notion integration token |
| `NOTION_PAGE_ID` | The 32-char hex ID from your Notion page URL |
| `SCREENSHOTS_FOLDER` | Path to your screenshots folder |
| `MONTHS_BACK` | How many months back to scan (default: 3) |

### 3. Connect Notion

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) and create a new integration
2. Copy the token into your `.env`
3. Open the Notion page where you want the to-dos
4. Click **"..."** > **"Connect to"** > select your integration

### 4. Run

```bash
# Analyze screenshots and create Notion to-do page
python agent.py

# After checking off items in Notion, archive them
python agent.py --archive
```

## Features

- **Collapsible sections** — Each category is a toggle heading you can expand/collapse; Archive section is collapsible too
- **Quick navigation** — Table of contents at the top lets you jump to any section
- **Smart pre-filtering** — Uses iPhone screen dimension matching to skip regular photos, saving API costs
- **Live section counts** — Running `--archive` updates each heading's item count to reflect remaining tasks
- **Resume support** — If interrupted (network error, rate limit), re-running picks up where it left off
- **Retry logic** — Automatic retries with exponential backoff on transient API errors
- **Batch Notion uploads** — Handles Notion's 100-block-per-request limit automatically
- **HEIC support** — Handles iPhone's native HEIC image format (Windows 11 built-in codec)

## Finding Your Screenshots Folder

| Platform | Typical Path |
|---|---|
| **Windows (iCloud)** | `C:/Users/YourName/iCloudPhotos/Photos` |
| **macOS** | Use `osxphotos` library, or `~/Pictures/Photos Library.photoslibrary` |
| **Manual export** | Any folder — just point `SCREENSHOTS_FOLDER` to it |

## Cost Estimate

Each screenshot analysis uses ~1,500 input tokens (image + prompt) and ~200 output tokens with Claude Sonnet. For 100 screenshots, expect roughly **$0.50–$1.00** in API costs.

## Tech Stack

- **Claude Sonnet 4.6** — Vision API for screenshot analysis
- **Notion API** — Structured to-do page creation
- **Pillow** — Image processing and HEIC support
- **Python 3.12** — Core runtime

## License

MIT
