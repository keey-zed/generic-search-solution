import os
import time
import base64
import io
import json
import random
import threading
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
import fitz  # PyMuPDF
from PIL import Image


# ============================================================
# Helpers
# ============================================================

def _int_from_gradio_number(x, default: int = 1) -> int:
    """Gradio Number typically yields float. Convert safely to int."""
    try:
        return int(float(x))
    except Exception:
        return int(default)


def _atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """Write text atomically (temp file in same dir, then os.replace)."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)

    base = os.path.basename(path)
    tmp_path = os.path.join(folder, f".{base}.tmp.{random.randint(100000, 999999)}")

    with open(tmp_path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)

    os.replace(tmp_path, path)


def _needs_ocr(txt_path: str) -> bool:
    """OCR needed if file missing, empty, unreadable, or only whitespace."""
    if not os.path.exists(txt_path):
        return True
    if os.path.getsize(txt_path) == 0:
        return True
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            sample = f.read(500)
        return not sample.strip()
    except Exception:
        return True


# ============================================================
# OpenRouter wrapper
# ============================================================

class OpenRouterAPIError(RuntimeError):
    def __init__(self, status_code: int, payload: object, retry_after: Optional[float] = None):
        super().__init__(f"OpenRouter API error ({status_code}): {payload}")
        self.status_code = status_code
        self.payload = payload
        self.retry_after = retry_after


@dataclass
class _OpenRouterResponse:
    text: str = ""


class OpenRouterGenerativeModel:
    """
    Minimal wrapper for:
      response = model.generate_content([prompt, pil_image], generation_config=gen_conf)
      extracted_text = response.text

    Thread-safe: one requests.Session per thread.
    """
    def __init__(self, model_name: str, api_key: str, referer: str = "", title: str = ""):
        self.model_name = model_name
        self.api_key = api_key
        self.referer = referer or "http://localhost"
        self.title = title or "PDF OCR"
        self._tls = threading.local()

    def _get_session(self) -> requests.Session:
        s = getattr(self._tls, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.referer,
                "X-Title": self.title,
            })
            self._tls.session = s
        return s

    @staticmethod
    def _pil_to_data_url(image: Image.Image, prefer_format: str = "JPEG") -> str:
        fmt = (prefer_format or "JPEG").upper()
        if fmt not in {"PNG", "JPEG", "JPG", "WEBP"}:
            fmt = "JPEG"

        buf = io.BytesIO()
        save_kwargs = {}
        if fmt in {"JPEG", "JPG"}:
            if image.mode in ("RGBA", "LA"):
                image = image.convert("RGB")
            save_kwargs["quality"] = 92
            save_kwargs["optimize"] = True

        image.save(buf, format="JPEG" if fmt == "JPG" else fmt, **save_kwargs)

        mime = "image/jpeg" if fmt in {"JPEG", "JPG"} else f"image/{fmt.lower()}"
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    def generate_content(self, parts, generation_config=None) -> _OpenRouterResponse:
        if not isinstance(parts, (list, tuple)) or len(parts) < 2:
            raise ValueError("generate_content expects [prompt, image]")

        prompt, image = parts[0], parts[1]
        if not isinstance(prompt, str):
            raise ValueError("First element must be a prompt string")
        if not isinstance(image, Image.Image):
            raise ValueError("Second element must be a PIL.Image.Image")

        # Max output tokens
        max_tokens = None
        if generation_config is not None:
            if isinstance(generation_config, dict):
                max_tokens = generation_config.get("max_output_tokens")
            else:
                max_tokens = getattr(generation_config, "max_output_tokens", None)
        if max_tokens is None:
            max_tokens = 2048

        max_tokens = int(max_tokens)
        max_tokens = min(max_tokens, 8192)

        data_url = self._pil_to_data_url(image, prefer_format="JPEG")

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }

        resp = self._get_session().post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            timeout=120,
        )

        if resp.status_code >= 400:
            retry_after = None
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    retry_after = float(ra)  # seconds
                except Exception:
                    retry_after = None

            try:
                err = resp.json()
            except Exception:
                err = {"error": resp.text}

            raise OpenRouterAPIError(resp.status_code, err, retry_after=retry_after)

        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Invalid JSON response: {e} | body={resp.text[:500]}")

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            raise RuntimeError(f"Unexpected OpenRouter response shape: {data}")

        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(item.get("text", ""))
                elif isinstance(item, str):
                    chunks.append(item)
            content = "\n".join([c for c in chunks if c is not None])

        return _OpenRouterResponse(text=str(content or ""))


# ============================================================
# Image prep + PDF render
# ============================================================

try:
    _LANCZOS = Image.Resampling.LANCZOS  # Pillow >= 10
except Exception:
    _LANCZOS = Image.LANCZOS


def _prepare_image_for_ocr(img: Image.Image,
                           max_pixels: int = 40_000_000,
                           max_side: int = 8000) -> Image.Image:
    """Downscale only if needed to keep images OCR-friendly and avoid huge payloads."""
    w, h = img.size
    pixels = w * h
    scale = 1.0

    if pixels > max_pixels:
        scale = min(scale, (max_pixels / float(pixels)) ** 0.5)

    longest = max(w, h)
    if longest * scale > max_side:
        scale = min(scale, max_side / float(longest))

    if scale < 1.0:
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img = img.resize((new_w, new_h), resample=_LANCZOS)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    return img


def _render_pdf_page_to_pil(pdf_path: str, page_index_0_based: int, zoom: float) -> Image.Image:
    """
    Render a single PDF page to a PIL image.
    Opens the PDF inside the function to avoid cross-thread document use.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index_0_based)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)  # alpha=False -> RGB
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


# ============================================================
# Legacy utility functions (kept for drop-in compatibility)
# ============================================================

def pdf_to_images(pdf_path: str, output_folder: str, book_name: str, zoom: float = 4.0) -> None:
    """Convert PDF pages to JPEG images."""
    os.makedirs(output_folder, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        for page_number in range(len(doc)):
            page = doc.load_page(page_number)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img = _prepare_image_for_ocr(img)
            image_filename = f"{book_name}_{page_number + 1}.jpg"
            image_path = os.path.join(output_folder, image_filename)
            img.save(image_path, format="JPEG", quality=92, optimize=True)
            print(f"Saved {image_path}")
    finally:
        doc.close()


def process_pdf_range(pdf_path: str,
                      output_folder: str,
                      book_name: str,
                      start_page: int,
                      end_page,
                      zoom: float = 4.0):
    """Convert a range of PDF pages to JPEG images."""
    os.makedirs(output_folder, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
        start_page = max(1, int(start_page))

        if end_page is None or end_page == "ALL" or end_page == "":
            end_page = total_pages
        else:
            try:
                end_page = int(end_page)
            except Exception:
                end_page = total_pages
            end_page = min(total_pages, end_page)

        start_idx = start_page - 1
        end_idx = end_page - 1

        for page_number in range(start_idx, end_idx + 1):
            page = doc.load_page(page_number)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img = _prepare_image_for_ocr(img)
            image_filename = f"{book_name}_{page_number + 1}.jpg"
            image_path = os.path.join(output_folder, image_filename)
            img.save(image_path, format="JPEG", quality=92, optimize=True)
            print(f"Saved {image_path}")

        return start_page, end_page
    finally:
        doc.close()


# ============================================================
# OCR pipeline
# ============================================================

API_CONCURRENCY = int(os.getenv("OPENROUTER_CONCURRENCY", "3"))
api_sem = threading.Semaphore(max(1, API_CONCURRENCY))

NUM_WORKERS = int(os.getenv("OCR_WORKERS", "4"))
MAX_WORKERS = max(1, min(NUM_WORKERS, API_CONCURRENCY))

RENDER_ZOOM = float(os.getenv("PDF_RENDER_ZOOM", "4"))
SAVE_RENDERED_IMAGES = os.getenv("SAVE_RENDERED_IMAGES", "0").strip().lower() in ("1", "true", "yes")


def process_image(pil_image: Image.Image, output_text_path: str, retries: int = 3) -> None:
    """
    OCR a PIL image and write its text to output_text_path (atomic).
    Retries on transient OpenRouter / network errors with backoff + jitter.
    """
    last_err: Optional[BaseException] = None
    image = _prepare_image_for_ocr(pil_image)

    for attempt in range(1, retries + 1):
        try:
            with api_sem:
                response = model.generate_content([OCR_PROMPT, image], generation_config=gen_conf)

            extracted_text = response.text or ""
            _atomic_write_text(output_text_path, extracted_text, encoding="utf-8")
            return

        except OpenRouterAPIError as e:
            last_err = e
            retryable = e.status_code in (408, 409, 425, 429, 500, 502, 503, 504)
            if (not retryable) or attempt == retries:
                break

            if e.retry_after is not None:
                sleep_s = max(0.5, float(e.retry_after))
            else:
                base = 1.5
                cap = 20.0
                sleep_s = min(cap, base * (2 ** (attempt - 1))) + random.uniform(0.0, 0.75)
            time.sleep(sleep_s)

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            last_err = e
            if attempt == retries:
                break
            base = 1.5
            cap = 20.0
            sleep_s = min(cap, base * (2 ** (attempt - 1))) + random.uniform(0.0, 0.75)
            time.sleep(sleep_s)

        except Exception as e:
            last_err = e
            if attempt == retries:
                break
            base = 1.0
            cap = 10.0
            sleep_s = min(cap, base * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5)
            time.sleep(sleep_s)

    raise RuntimeError(f"OCR failed after {retries} attempts. Last error: {last_err}")


def ocr_pdf_page(pdf_path: str,
                 base_name: str,
                 page_num_1_based: int,
                 img_folder: str,
                 txt_folder: str,
                 zoom: float,
                 retries: int = 3) -> None:
    """Render+OCR a single page, writing text atomically."""
    output_text_path = os.path.join(txt_folder, f"{base_name}_{page_num_1_based}.txt")
    if not _needs_ocr(output_text_path):
        return

    print(f"OCR page {page_num_1_based} ...")
    pil_img = _render_pdf_page_to_pil(pdf_path, page_num_1_based - 1, zoom=zoom)

    if SAVE_RENDERED_IMAGES:
        os.makedirs(img_folder, exist_ok=True)
        img_path = os.path.join(img_folder, f"{base_name}_{page_num_1_based}.jpg")
        _prepare_image_for_ocr(pil_img).save(img_path, format="JPEG", quality=92, optimize=True)

    process_image(pil_img, output_text_path=output_text_path, retries=retries)
    print(f"Done page {page_num_1_based}")


# ============================================================
# Post-processing
# ============================================================

def clean_unnecessary_linebreaks(text: str) -> str:
    """
    1) Preserves page separators (=== Page X ===)
    2) Keeps line breaks only when previous line ends with '.' or ':'
    3) Removes other line breaks within pages by merging with a space
    """
    lines = text.split("\n")
    cleaned = []

    def _keep_break(prev_line: str) -> bool:
        prev = prev_line.rstrip()
        return prev.endswith(".") or prev.endswith(":")

    for i, line in enumerate(lines):
        if line.startswith("=== Page"):
            cleaned.append(line)
            if i + 1 < len(lines) and lines[i + 1].strip() == "":
                cleaned.append("")
            continue

        if i > 0 and not lines[i - 1].startswith("=== Page") and not _keep_break(lines[i - 1]):
            if cleaned and cleaned[-1] != "":
                cleaned[-1] = cleaned[-1].rstrip() + " " + line.lstrip()
            else:
                cleaned.append(line)
        else:
            cleaned.append(line)

    return "\n".join(cleaned)



def ocr_pdf_interface(pdf_file, start_page, end_page):
    try:
        pdf_path = pdf_file.name
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]

        img_folder = f"tempo_{base_name}"
        txt_folder = f"tempo_res_{base_name}"
        os.makedirs(txt_folder, exist_ok=True)
        if SAVE_RENDERED_IMAGES:
            os.makedirs(img_folder, exist_ok=True)

        # total pages
        doc = fitz.open(pdf_path)
        try:
            total_pages = len(doc)
        finally:
            doc.close()

        sp = max(1, _int_from_gradio_number(start_page, default=1))

        if end_page in [None, "ALL", ""]:
            ep = total_pages
        else:
            try:
                ep = int(str(end_page).strip())
            except Exception:
                ep = total_pages
            ep = min(total_pages, ep)

        if sp > ep:
            sp, ep = ep, sp

        pages = list(range(sp, ep + 1))

        # schedule only needed pages
        to_run = []
        skipped = 0
        for p in pages:
            out_path = os.path.join(txt_folder, f"{base_name}_{p}.txt")
            if _needs_ocr(out_path):
                to_run.append(p)
            else:
                skipped += 1

        print(f"Selected pages: {sp}-{ep} | to OCR: {len(to_run)} | skipped (cached): {skipped}")
        if to_run:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futs = {
                    ex.submit(ocr_pdf_page, pdf_path, base_name, p, img_folder, txt_folder, RENDER_ZOOM): p
                    for p in to_run
                }
                for fut in as_completed(futs):
                    p = futs[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        print(f"Page {p} failed: {e}")
                        out_path = os.path.join(txt_folder, f"{base_name}_{p}.txt")
                        if _needs_ocr(out_path):
                            _atomic_write_text(out_path, f"[OCR failed for this page: {e}]\n")

        # combine
        combined = []
        for p in pages:
            text_path = os.path.join(txt_folder, f"{base_name}_{p}.txt")
            if os.path.exists(text_path):
                with open(text_path, "r", encoding="utf-8") as f:
                    combined.append(f"=== Page {p} ===\n{f.read()}\n")
            else:
                combined.append(f"=== Page {p} ===\n[OCR failed for this page]\n")

        raw = "\n".join(combined)
        #return clean_unnecessary_linebreaks(raw)
        return raw

    except Exception as e:
        return f"Error during processing: {e}"


# ============================================================
# Configuration + prompt
# ============================================================

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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").strip()
if not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_KEY environment variable")

model_name = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
YOUR_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost")
YOUR_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "PDF OCR")

model = OpenRouterGenerativeModel(
    model_name=model_name,
    api_key=OPENROUTER_API_KEY,
    referer=YOUR_SITE_URL,
    title=YOUR_SITE_NAME,
)

class GenerationConfig:
    def __init__(self, max_output_tokens: int):
        self.max_output_tokens = max_output_tokens

MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "8192"))
gen_conf = GenerationConfig(max_output_tokens=MAX_OUTPUT_TOKENS)

OCR_PROMPT = """# Image Text Extraction Prompt

## Objective

Extract all visible text from the image with high fidelity to the original content.

## Text Representation Guidelines

### Plain Text

* Transcribe all visible text precisely as it appears.
* Minimize unnecessary line breaks:

  * Preserve line breaks only when they clearly indicate the end of a sentence (e.g., a period followed by a new line).
  * Otherwise, produce clean and continuous paragraphs.

### Tables

* Represent all tables using Markdown table syntax.
* Preserve the table’s structure, alignment, and headers as accurately as possible.

## Layout and Formatting Preservation

### Structure

* Reconstruct the logical and visual structure of the original content.
* When clear sections, subsections, or subsubsections are visually or typographically indicated, convert them using:
  * # for sections
  * ## for subsections
  * ### for subsubsections

### Header Formatting Rules

* Only use headers when they denote true structural divisions.
* Do not use headers for mere itemized lists, figure labels, or emphasized phrases.
* Retain original title hierarchy and nesting where visually or contextually evident.
* Do not include top-of-page running headers that are not part of the main document content.

## Fidelity

* Preserve indentation, bullet points, and numbered lists when present in the original layout.
* Emphasize textual elements only if clearly used for hierarchy or emphasis in the source.
* Preserve any separating horizontal line exactly as it appears in the source document.
* DO NOT TRANSLATE OR INTERPRET!!! YOU NEED TO EXTRACT THE TEXT EXACTLY AS IT APPEARS.


## Special Cases

* If the page is a table of contents, do not process it — skip OCR for that page.

## Presence of diagrams

In many cases there are diagrams, please try to write a text that reflects the ideas behind these diagrams.
"""


