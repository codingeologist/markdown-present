from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image as PILImage, ImageOps
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Footer, Header, Markdown, Static
from textual_image.widget import Image

IMAGE_LINE = re.compile(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$")
"""Matches a markdown line containing only an image: ![alt](path)"""


class SlideContainer(VerticalScroll):
    """A scrollable container for a slide.

    Only binds the vertical scroll keys, so that left/right and home/end
    fall through to the app-level slide navigation bindings.
    """

    BINDINGS = [
        Binding("up", "scroll_up", "Scroll Up"),
        Binding("down", "scroll_down", "Scroll Down"),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]


class MarkdownSlidesApp(App):
    """A presentation tool: each H2 (##) in the markdown file is one slide,
    with the H1 (#) title on its own slide."""

    BINDINGS = [
        Binding("right", "next_slide", "Next Slide", tooltip="Next slide"),
        Binding("left", "previous_slide", "Previous Slide", tooltip="Previous slide"),
        Binding("home", "first_slide", "First Slide", show=False),
        Binding("end", "last_slide", "Last Slide", show=False),
        Binding("?", "help", "Help", tooltip="Show help"),
    ]

    CSS = """
    SlideContainer {
        padding: 0 2;
    }
    SlideContainer Image {
        margin: 1 0;
    }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.slides: list[str] = []
        self.slide_number = 0

    @property
    def slide_container(self) -> SlideContainer:
        """Get the slide container widget."""
        return self.query_one(SlideContainer)

    def compose(self) -> ComposeResult:
        yield Header()
        yield SlideContainer()
        yield Footer()

    def load_slides(self, path: Path) -> None:
        """Split the markdown file into slides.

        The H1 (#) title gets its own slide, and each H2 (##) section
        (including its nested content, up to the next heading) is a slide.
        """
        text = path.read_text(encoding="utf-8")
        slides: list[str] = []
        current: list[str] = []
        in_code_block = False

        def flush() -> None:
            if any(ln.strip() for ln in current):
                slides.append("\n".join(current).strip())
            current.clear()

        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                in_code_block = not in_code_block
            if not in_code_block and (line.startswith("# ") or line.startswith("## ")):
                flush()
            current.append(line)
        flush()
        self.slides = slides

    def parse_slide(self, slide: str) -> list[tuple[str, str]]:
        """Split a slide into a sequence of ("markdown" | "image", content) chunks.

        Lines containing only an image reference become image chunks; all
        other lines are grouped into markdown chunks.
        """
        chunks: list[tuple[str, str]] = []
        markdown_lines: list[str] = []
        in_code_block = False

        def flush_markdown() -> None:
            if any(ln.strip() for ln in markdown_lines):
                chunks.append(("markdown", "\n".join(markdown_lines).strip()))
            markdown_lines.clear()

        for line in slide.splitlines():
            if line.lstrip().startswith("```"):
                in_code_block = not in_code_block
            if not in_code_block:
                match = IMAGE_LINE.match(line)
                if match:
                    flush_markdown()
                    chunks.append(("image", match.group(1)))
                    continue
            markdown_lines.append(line)
        flush_markdown()
        return chunks

    def image_widget(self, source: str) -> Image:
        """Create an Image widget, resolving the source path relative to
        the markdown file. Falls back to an error message if it can't load."""
        path = Path(source)
        if not path.is_absolute():
            path = self.path.parent / path

        def on_error(error: Exception) -> Widget:
            return Static(
                f"⚠ Unable to load image '{path}' ({error})", classes="image-error"
            )

        try:
            # Open with Pillow and apply the EXIF orientation, so photos from
            # phones / cameras are displayed the right way up.
            with PILImage.open(path) as image:
                image = ImageOps.exif_transpose(image)
                return Image(image, on_error=on_error)
        except Exception:
            # File missing or not an image: let the widget show the error.
            return Image(str(path), on_error=on_error)

    async def on_mount(self) -> None:
        """Load the file and show the first slide when the app starts."""
        try:
            self.load_slides(self.path)
        except FileNotFoundError:
            self.exit(message=f"Unable to load {self.path!r}")
            return
        if not self.slides:
            self.exit(message=f"No H1 (#) or H2 (##) headings found in {self.path!r}")
            return
        await self.show_slide(0)

    async def show_slide(self, slide_number: int) -> None:
        """Display the slide at the given index and update the title."""
        self.slide_number = max(0, min(slide_number, len(self.slides) - 1))
        container = self.slide_container
        # Rebuild the slide content from scratch
        await container.remove_children()
        for chunk_type, content in self.parse_slide(self.slides[self.slide_number]):
            if chunk_type == "image":
                await container.mount(self.image_widget(content))
            else:
                await container.mount(Markdown(content))
        # Start each slide at the top, with keyboard focus on the scroll
        # container so up/down scroll within the slide.
        container.scroll_to(y=0, animate=False)
        container.focus()
        self.sub_title = (
            f"{self.path.name} — slide {self.slide_number + 1}/{len(self.slides)}"
        )
        self.refresh_bindings()

    async def action_next_slide(self) -> None:
        """Navigate to the next slide."""
        await self.show_slide(self.slide_number + 1)

    async def action_previous_slide(self) -> None:
        """Navigate to the previous slide."""
        await self.show_slide(self.slide_number - 1)

    async def action_first_slide(self) -> None:
        """Navigate to the first slide."""
        await self.show_slide(0)

    async def action_last_slide(self) -> None:
        """Navigate to the last slide."""
        await self.show_slide(len(self.slides) - 1)

    def check_action(self, action: str, _) -> bool | None:
        """Disable footer keys when they would have no effect."""
        if action == "next_slide" and self.slide_number >= len(self.slides) - 1:
            return None
        if action == "previous_slide" and self.slide_number <= 0:
            return None
        return True


def main() -> None:
    """Parse command line arguments and run the presentation app."""
    parser = argparse.ArgumentParser(
        description=(
            "Present a markdown file as slides: the H1 (#) title gets its own "
            "slide, and each H2 (##) section is a slide."
        )
    )
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        required=True,
        metavar="MARKDOWN_FILE",
        help="Path to the markdown file to present",
    )
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error(f"file does not exist: {args.file}")
    app = MarkdownSlidesApp(args.file)
    app.run()


if __name__ == "__main__":
    main()
