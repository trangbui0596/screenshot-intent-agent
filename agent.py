"""
Screenshot Intent Agent
Scans iPhone screenshots, analyzes intent with Claude Vision,
and creates categorized to-do items in Notion.
"""

import os
import sys
import base64
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from io import BytesIO

import anthropic
from notion_client import Client as NotionClient
from dotenv import load_dotenv
from PIL import Image

# Check HEIC support (Windows 11 usually has the codec built-in)
HEIC_SUPPORTED = False
try:
    from PIL import features
    # Pillow can read HEIF via the built-in Windows codec on Win11
    HEIC_SUPPORTED = True
except Exception:
    pass

_script_dir = Path(__file__).resolve().parent
load_dotenv(_script_dir / ".env", override=True)

# Fix Windows console encoding for emoji output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
SCREENSHOTS_FOLDER = os.getenv("SCREENSHOTS_FOLDER")
MONTHS_BACK = int(os.getenv("MONTHS_BACK", "3"))
MAX_IMAGE_SIZE = (1568, 1568)  # Claude vision max recommended size

CATEGORIES = {
    "networking": {
        "emoji": "🤝",
        "color": "blue",
        "description": "People to reach out to",
    },
    "research": {
        "emoji": "🔬",
        "color": "purple",
        "description": "Topics to research deeper",
    },
    "synthesis": {
        "emoji": "💡",
        "color": "yellow",
        "description": "Ideas to synthesize into operating principles",
    },
    "follow_up": {
        "emoji": "📌",
        "color": "red",
        "description": "Items requiring follow-up action",
    },
    "reference": {
        "emoji": "📚",
        "color": "green",
        "description": "Reference material to save",
    },
    "other": {
        "emoji": "📋",
        "color": "gray",
        "description": "Other actionable items",
    },
}

ANALYSIS_PROMPT = """\
You are analyzing a screenshot from someone's iPhone. Your job is to infer \
WHY they took this screenshot — what intent or interest it signals — and \
produce a concrete, actionable to-do item.

## Categories

- **networking**: Screenshot of a person's profile, bio, contact info, or \
conversation about connecting with someone. → Action: reach out, connect, \
follow up with this person.
- **research**: Screenshot of a company page, product, presentation slide, \
industry report, or technical content. → Action: research this topic/company \
further.
- **synthesis**: Screenshot of an article, quote, opinion piece, book \
passage, tweet thread, or thought-provoking content. → Action: read deeply, \
extract lessons, integrate into thinking or operating principles.
- **follow_up**: Screenshot of a to-do, reminder, event, booking, receipt, \
confirmation, or conversation requiring action. → Action: follow up on this \
specific item.
- **reference**: Screenshot of settings, instructions, code, recipes, \
addresses, or other reference material. → Action: file for future reference.
- **other**: Anything that doesn't fit above but still has a clear intent.

## Instructions

1. Look carefully at the screenshot content.
2. Determine the most likely category.
3. Extract the key details (names, topics, dates, URLs if visible).
4. Write a specific, actionable to-do item (not vague).

## Response format (strict JSON)

{
  "category": "one of: networking, research, synthesis, follow_up, reference, other",
  "title": "Short title for the to-do item (under 80 chars)",
  "action": "Specific action to take (1-2 sentences)",
  "details": "Key details extracted from the screenshot (names, topics, dates, etc.)",
  "confidence": "high, medium, or low — how confident you are in the categorization",
  "skip": false
}

If the screenshot is not actionable (e.g., a meme, a game, a random UI glitch), \
set "skip": true and leave other fields minimal.

Return ONLY the JSON object, no markdown fencing.
"""


# ---------------------------------------------------------------------------
# Screenshot Scanner
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp"}


def find_screenshots(folder: str, months_back: int) -> list[Path]:
    """Find image files in folder modified within the last N months."""
    folder_path = Path(folder)
    if not folder_path.exists():
        print(f"Error: Folder not found: {folder}")
        sys.exit(1)

    cutoff = datetime.now() - timedelta(days=months_back * 30)
    screenshots = []

    for file in folder_path.rglob("*"):
        if file.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if not file.is_file():
            continue
        mod_time = datetime.fromtimestamp(file.stat().st_mtime)
        if mod_time >= cutoff:
            screenshots.append(file)

    screenshots.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return screenshots


# Common iPhone screenshot resolutions (width x height, portrait)
IPHONE_SCREENSHOT_SIZES = {
    (1170, 2532),  # iPhone 12/13/14 Pro
    (1179, 2556),  # iPhone 14/15 Pro
    (1206, 2622),  # iPhone 16 Pro
    (1290, 2796),  # iPhone 14/15 Pro Max
    (1320, 2868),  # iPhone 16 Pro Max
    (1125, 2436),  # iPhone X/XS/11 Pro
    (1242, 2688),  # iPhone XS Max/11 Pro Max
    (1284, 2778),  # iPhone 12/13/14 Pro Max
    (1080, 1920),  # iPhone 6+/7+/8+
    (750, 1334),   # iPhone 6/7/8/SE2/SE3
    (1170, 2532),  # iPhone 12/13/14
    (828, 1792),   # iPhone XR/11
    (1242, 2208),  # iPhone 6s+/7+/8+ (3x)
    (640, 1136),   # iPhone 5/5s/SE1
}


def is_likely_screenshot(path: Path) -> bool:
    """Check if an image has iPhone screenshot dimensions."""
    try:
        with Image.open(path) as img:
            w, h = img.size
            # Ensure portrait orientation
            if w > h:
                w, h = h, w
            # Exact match to known iPhone sizes
            if (w, h) in IPHONE_SCREENSHOT_SIZES:
                return True
            # Fallback: iPhone screenshots are always portrait with ~9:19.5 ratio
            ratio = h / w if w > 0 else 0
            if 1.7 < ratio < 2.3 and w >= 640:
                return True
            return False
    except Exception:
        return False


def image_to_base64(path: Path) -> tuple[str, str]:
    """Load an image, resize if needed, and return (base64_data, media_type)."""
    img = Image.open(path)

    # Convert HEIC/palette/RGBA to RGB
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too large
    img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    b64 = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return b64, "image/jpeg"


# ---------------------------------------------------------------------------
# Claude Vision Analyzer
# ---------------------------------------------------------------------------


def analyze_screenshot(client: anthropic.Anthropic, path: Path) -> dict | None:
    """Send a screenshot to Claude for analysis."""
    try:
        b64_data, media_type = image_to_base64(path)
    except Exception as e:
        print(f"  ⚠ Could not load image {path.name}: {e}")
        return None

    # Retry up to 3 times on transient network errors
    last_err = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64_data,
                                },
                            },
                            {"type": "text", "text": ANALYSIS_PROMPT},
                        ],
                    }
                ],
            )
            break
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as e:
            last_err = e
            wait = 2 ** attempt * 5  # 5s, 10s, 20s
            print(f"  ⚠ {type(e).__name__}, retrying in {wait}s (attempt {attempt + 1}/3)...")
            time.sleep(wait)
    else:
        print(f"  ⚠ Failed after 3 retries for {path.name}: {last_err}")
        return None

    raw = response.content[0].text.strip()

    # Handle cases where model wraps in markdown
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    try:
        result = json.loads(raw)
        result["source_file"] = str(path)
        result["file_date"] = datetime.fromtimestamp(
            path.stat().st_mtime
        ).strftime("%Y-%m-%d")
        return result
    except json.JSONDecodeError:
        print(f"  ⚠ Could not parse Claude response for {path.name}")
        return None


# ---------------------------------------------------------------------------
# Notion Integration
# ---------------------------------------------------------------------------


def create_notion_todo_page(notion: NotionClient, page_id: str, results: list[dict]):
    """Create a subpage in Notion with categorized to-do items."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Group results by category
    by_category: dict[str, list[dict]] = {}
    for item in results:
        cat = item.get("category", "other")
        by_category.setdefault(cat, []).append(item)

    # Build the page content as blocks
    children = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"type": "emoji", "emoji": "📱"},
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"Auto-generated from {len(results)} screenshots analyzed on {today}"
                        },
                    }
                ],
            },
        },
        # Table of contents for quick navigation
        {
            "object": "block",
            "type": "table_of_contents",
            "table_of_contents": {"color": "gray"},
        },
        {"object": "block", "type": "divider", "divider": {}},
    ]

    for cat_key, cat_info in CATEGORIES.items():
        items = by_category.get(cat_key, [])
        if not items:
            continue

        heading_text = f"{cat_info['emoji']} {cat_key.replace('_', ' ').title()} ({len(items)})"

        # Build to-do blocks as children of the toggle heading
        todo_children = []
        for item in items:
            todo_children.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "checked": False,
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": item.get("title", "Untitled")},
                                "annotations": {"bold": True},
                            }
                        ],
                        "children": [
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        {
                                            "type": "text",
                                            "text": {
                                                "content": f"Action: {item.get('action', 'N/A')}"
                                            },
                                        }
                                    ]
                                },
                            },
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        {
                                            "type": "text",
                                            "text": {
                                                "content": f"Details: {item.get('details', 'N/A')}"
                                            },
                                            "annotations": {"color": "gray"},
                                        }
                                    ]
                                },
                            },
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        {
                                            "type": "text",
                                            "text": {
                                                "content": f"📅 {item.get('file_date', '?')} · 📁 {Path(item.get('source_file', '')).name}"
                                            },
                                            "annotations": {
                                                "color": "gray",
                                                "italic": True,
                                            },
                                        }
                                    ]
                                },
                            },
                        ],
                    },
                }
            )

        # Collapsible toggle heading (created empty, children added after)
        children.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "is_toggleable": True,
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": heading_text},
                        }
                    ],
                },
                "_todo_children": todo_children,  # stashed for later
            }
        )

    # Create the subpage with just the top-level blocks (no nested children yet)
    # Strip _todo_children before sending to Notion
    top_level = []
    deferred: list[tuple[int, list[dict]]] = []  # (index, children)
    for i, block in enumerate(children):
        todo_kids = block.pop("_todo_children", None)
        top_level.append(block)
        if todo_kids:
            deferred.append((i, todo_kids))

    first_batch = top_level[:100]
    remaining_top = top_level[100:]

    new_page = notion.pages.create(
        parent={"page_id": page_id},
        properties={
            "title": {
                "title": [
                    {
                        "text": {
                            "content": f"📱 Screenshot Actions — {today}"
                        }
                    }
                ]
            }
        },
        children=first_batch,
    )

    page_id_new = new_page["id"]

    # Append any remaining top-level blocks
    while remaining_top:
        batch = remaining_top[:100]
        remaining_top = remaining_top[100:]
        notion.blocks.children.append(block_id=page_id_new, children=batch)

    # Now fetch all blocks to get the toggle heading IDs, then append children
    all_page_blocks = get_all_children(notion, page_id_new)
    toggle_headings = [
        b for b in all_page_blocks
        if b["type"] == "heading_2"
        and b["heading_2"].get("is_toggleable")
    ]

    # Match toggle headings to deferred children by order
    for toggle_block, (_, todo_kids) in zip(toggle_headings, deferred):
        toggle_id = toggle_block["id"]
        remaining_kids = list(todo_kids)
        while remaining_kids:
            batch = remaining_kids[:100]
            remaining_kids = remaining_kids[100:]
            notion.blocks.children.append(block_id=toggle_id, children=batch)

    return new_page["id"], new_page["url"]


# ---------------------------------------------------------------------------
# Archive: move checked to-dos to an Archive section
# ---------------------------------------------------------------------------

ARCHIVE_HEADING_TEXT = "🗄️ Archive"


def find_archive_heading(notion: NotionClient, page_id: str) -> str | None:
    """Find the Archive heading block ID if it already exists."""
    cursor = None
    while True:
        resp = notion.blocks.children.list(
            block_id=page_id, start_cursor=cursor, page_size=100
        )
        for block in resp["results"]:
            if block["type"] == "heading_2":
                texts = block["heading_2"].get("rich_text", [])
                if texts and ARCHIVE_HEADING_TEXT in texts[0].get("text", {}).get("content", ""):
                    return block["id"]
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
    return None


def get_all_children(notion: NotionClient, page_id: str) -> list[dict]:
    """Fetch all top-level children blocks of a page."""
    blocks = []
    cursor = None
    while True:
        resp = notion.blocks.children.list(
            block_id=page_id, start_cursor=cursor, page_size=100
        )
        blocks.extend(resp["results"])
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
    return blocks


def get_block_children(notion: NotionClient, block_id: str) -> list[dict]:
    """Fetch children of a specific block."""
    blocks = []
    cursor = None
    while True:
        resp = notion.blocks.children.list(
            block_id=block_id, start_cursor=cursor, page_size=100
        )
        blocks.extend(resp["results"])
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
    return blocks


def rebuild_todo_block(todo_block: dict, children: list[dict]) -> dict:
    """Rebuild a to-do block for appending (strip read-only fields)."""
    td = todo_block["to_do"]
    rich_text = td.get("rich_text", [])

    # Clean rich_text: keep only type, text, and annotations
    cleaned_rt = []
    for rt in rich_text:
        entry = {"type": "text", "text": rt.get("text", {"content": ""})}
        if "annotations" in rt:
            entry["annotations"] = rt["annotations"]
        cleaned_rt.append(entry)

    # Rebuild children blocks (paragraphs under the to-do)
    cleaned_children = []
    for child in children:
        if child["type"] == "paragraph":
            child_rt = []
            for rt in child["paragraph"].get("rich_text", []):
                entry = {"type": "text", "text": rt.get("text", {"content": ""})}
                if "annotations" in rt:
                    entry["annotations"] = rt["annotations"]
                child_rt.append(entry)
            cleaned_children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": child_rt},
            })

    block = {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "checked": True,
            "rich_text": cleaned_rt,
        },
    }
    if cleaned_children:
        block["to_do"]["children"] = cleaned_children
    return block


def update_heading_count(notion: NotionClient, heading_block: dict, new_count: int):
    """Update the count in a toggle heading like '🤝 Networking (12)' → '🤝 Networking (9)'."""
    import re
    texts = heading_block["heading_2"].get("rich_text", [])
    if not texts:
        return
    old_text = texts[0].get("text", {}).get("content", "")
    # Replace the (N) at the end, or append it
    new_text = re.sub(r"\s*\(\d+\)\s*$", "", old_text) + f" ({new_count})"
    notion.blocks.update(
        block_id=heading_block["id"],
        heading_2={
            "is_toggleable": True,
            "rich_text": [{"type": "text", "text": {"content": new_text}}],
        },
    )


def archive_checked_todos(notion_page_id: str):
    """Move all checked to-do items to an Archive section at the bottom."""
    notion = NotionClient(auth=NOTION_TOKEN)

    print("📖 Reading Notion page...")
    all_blocks = get_all_children(notion, notion_page_id)

    # Find checked to-dos and track which heading they belong to
    checked = []
    # Map heading block ID → (heading_block, [all inner blocks])
    heading_contents: dict[str, tuple[dict, list[dict]]] = {}

    for block in all_blocks:
        # Direct to-do at top level (legacy layout)
        if block["type"] == "to_do" and block["to_do"].get("checked"):
            children = []
            if block.get("has_children"):
                children = get_block_children(notion, block["id"])
            checked.append((block, children))

        # Toggle heading — look inside for checked to-dos
        elif block["type"] == "heading_2" and block.get("has_children"):
            inner_blocks = get_block_children(notion, block["id"])
            heading_contents[block["id"]] = (block, inner_blocks)
            for inner in inner_blocks:
                if inner["type"] == "to_do" and inner["to_do"].get("checked"):
                    children = []
                    if inner.get("has_children"):
                        children = get_block_children(notion, inner["id"])
                    checked.append((inner, children))

    if not checked:
        print("No checked items to archive.")
        return

    print(f"📦 Found {len(checked)} checked item(s) to archive")

    # Ensure Archive heading exists and is toggleable
    archive_id = find_archive_heading(notion, notion_page_id)
    if archive_id:
        # Check if existing archive heading is toggleable; if not, replace it
        archive_block = notion.blocks.retrieve(block_id=archive_id)
        if not archive_block.get("heading_2", {}).get("is_toggleable"):
            # Migrate existing children out, delete old heading, recreate as toggle
            old_children = []
            if archive_block.get("has_children"):
                old_children = get_block_children(notion, archive_id)
            notion.blocks.delete(block_id=archive_id)
            archive_id = None  # will be recreated below

    if not archive_id:
        print("   Creating Archive section...")
        resp = notion.blocks.children.append(
            block_id=notion_page_id,
            children=[
                {"object": "block", "type": "divider", "divider": {}},
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "is_toggleable": True,
                        "rich_text": [
                            {"type": "text", "text": {"content": ARCHIVE_HEADING_TEXT}}
                        ]
                    },
                },
            ],
        )
        archive_id = resp["results"][1]["id"]

    # Rebuild checked to-dos and append inside the archive toggle
    archive_blocks = [rebuild_todo_block(b, c) for b, c in checked]
    remaining_archive = list(archive_blocks)
    while remaining_archive:
        batch = remaining_archive[:100]
        remaining_archive = remaining_archive[100:]
        notion.blocks.children.append(block_id=archive_id, children=batch)

    # Delete the original checked blocks
    print("   Removing originals from active list...")
    checked_ids = {block["id"] for block, _ in checked}
    for block, _ in checked:
        notion.blocks.delete(block_id=block["id"])

    # Update heading counts to reflect remaining unchecked items
    print("   Updating section counts...")
    for heading_id, (heading_block, inner_blocks) in heading_contents.items():
        # Count to-dos that were NOT just archived
        remaining_count = sum(
            1 for b in inner_blocks
            if b["type"] == "to_do" and b["id"] not in checked_ids
        )
        update_heading_count(notion, heading_block, remaining_count)

    print(f"✅ Archived {len(checked)} completed item(s), section counts updated")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Validate config
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not NOTION_TOKEN:
        missing.append("NOTION_TOKEN")
    if not NOTION_PAGE_ID:
        missing.append("NOTION_PAGE_ID")
    if not SCREENSHOTS_FOLDER:
        missing.append("SCREENSHOTS_FOLDER")
    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    if not HEIC_SUPPORTED:
        print(
            "Note: HEIC support not available. iPhone photos in HEIC format "
            "will be skipped. Install pillow-heif to enable."
        )

    # 1. Scan for images and filter to likely screenshots
    print(f"\n📂 Scanning {SCREENSHOTS_FOLDER} (last {MONTHS_BACK} months)...")
    all_images = find_screenshots(SCREENSHOTS_FOLDER, MONTHS_BACK)
    print(f"   Found {len(all_images)} images total")

    print("🔎 Filtering to likely screenshots (by iPhone screen dimensions)...")
    screenshots = [p for p in all_images if is_likely_screenshot(p)]
    print(f"   → {len(screenshots)} likely screenshots (skipped {len(all_images) - len(screenshots)} regular photos)\n")

    if not screenshots:
        print("No screenshots found. Check your SCREENSHOTS_FOLDER path.")
        sys.exit(0)

    # 2. Analyze each screenshot with Claude (with resume support)
    progress_path = _script_dir / "progress.json"
    if progress_path.exists():
        with open(progress_path, "r", encoding="utf-8") as f:
            progress = json.load(f)
        results = progress.get("results", [])
        done_files = {r["source_file"] for r in results}
        skipped = progress.get("skipped", 0)
        done_skipped_files = set(progress.get("skipped_files", []))
        done_files.update(done_skipped_files)
        print(f"🔄 Resuming — {len(results)} items already analyzed, {skipped} skipped\n")
    else:
        results = []
        done_files = set()
        skipped = 0

    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    remaining = [p for p in screenshots if str(p) not in done_files]

    if not remaining:
        print("All screenshots already analyzed.\n")
    else:
        total = len(screenshots)
        start_idx = total - len(remaining) + 1
        for i, path in enumerate(remaining, start_idx):
            print(f"🔍 [{i}/{total}] Analyzing {path.name}...")
            analysis = analyze_screenshot(claude, path)

            if analysis is None:
                continue
            if analysis.get("skip"):
                skipped += 1
                done_files.add(str(path))
                print(f"   ⏭ Skipped (not actionable)")
            else:
                cat = analysis.get("category", "other")
                emoji = CATEGORIES.get(cat, CATEGORIES["other"])["emoji"]
                print(f"   {emoji} {analysis.get('title', '?')}")
                results.append(analysis)

            # Save progress after each screenshot
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump({
                    "results": results,
                    "skipped": skipped,
                    "skipped_files": [s for s in done_files if s not in {r["source_file"] for r in results}],
                }, f, ensure_ascii=False)

    print(f"\n✅ Analyzed {len(screenshots)} screenshots")
    print(f"   → {len(results)} actionable items, {skipped} skipped\n")

    if not results:
        print("No actionable items found.")
        sys.exit(0)

    # 3. Push to Notion
    print("📝 Creating Notion page...")
    notion = NotionClient(auth=NOTION_TOKEN)
    created_page_id, page_url = create_notion_todo_page(notion, NOTION_PAGE_ID, results)
    print(f"✅ Done! View your to-dos at:\n   {page_url}\n")

    # Save page ID so --archive can find it later
    with open(_script_dir / "last_page.json", "w") as f:
        json.dump({"page_id": created_page_id, "url": page_url}, f)

    # Save final results and clean up progress file
    output_path = _script_dir / "screenshot_analysis.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"💾 Local backup saved to {output_path}")

    # Remove progress file since we're done
    progress_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--archive":
        # Archive mode: move checked to-dos to Archive section
        # Accept optional page ID as second arg, otherwise use last created page
        if len(sys.argv) > 2:
            target_page = sys.argv[2]
        else:
            # Read from the saved state
            state_path = _script_dir / "last_page.json"
            if state_path.exists():
                with open(state_path, "r") as f:
                    target_page = json.load(f).get("page_id", NOTION_PAGE_ID)
            else:
                print("No previous page found. Pass the page ID:")
                print("  python agent.py --archive <notion-page-id>")
                sys.exit(1)
        archive_checked_todos(target_page)
    else:
        main()
