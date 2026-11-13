"""Local, non-destructive P0 verification with a user's ORIGINAL OnMap PDF.

This tool never uploads, saves, or modifies the source PDF. It validates
both export options from the same visible OCG state, compares every output
pixel against the original full-page export, and records reproducible JSON.

Examples (Windows CMD):
  python quality\validate_onmap_source_pdf.py "C:\\maps\\source.pdf" --page 1
  python quality\validate_onmap_source_pdf.py "C:\\maps\\source.pdf" --max-edge 5000 --out-dir "C:\\maps\\qa"
  python quality\validate_onmap_source_pdf.py "C:\\maps\\source.pdf" --layer-off "경계" --report "C:\\maps\\qa.json"
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import sys
import tempfile
from pathlib import Path

# A CMD invocation from the repo root needn't install an editable package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz
from PIL import Image

from drawing_editor.core import DrawingDocument, DrawingError, OutputOptions
from drawing_editor.trim import image_ink_bbox


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(piece)
    return digest.hexdigest()


def validate(source: Path, page_number: int, max_edge: int, off_names, folder: Path):
    """Verify that crop pixels equal the full-page pixels of the same OCG state."""
    source = source.expanduser().resolve(strict=True)
    if source.suffix.lower() != '.pdf':
        raise ValueError('An original PDF file is required.')
    if not 256 <= max_edge <= 8000:
        raise ValueError('--max-edge must be between 256 and 8000.')
    initial_hash = sha256(source)
    with fitz.open(source) as original:
        if not original.is_pdf or original.needs_pass:
            raise ValueError('PDF is encrypted or unsupported.')
        if not 1 <= page_number <= original.page_count:
            raise ValueError('Selected page is outside the PDF page range.')
        ocg_count = len(original.get_ocgs() or {})
        all_pages = original.page_count
    with DrawingDocument(source) as doc:
        doc.page_index = page_number - 1
        if off_names:
            layers = doc.layers()
            for name in off_names:
                matches = [layer for layer in layers if layer.name == name]
                if len(matches) != 1:
                    raise ValueError(f'Layer name must match exactly once: {name!r}')
                doc.set_visibility(matches[0].key, False)
        state = [{'name': layer.name, 'visible': layer.visible, 'locked': layer.locked}
                 for layer in doc.layers()]
        output = []
        transparent_bbox = None
        for background in ('transparent', 'opaque'):
            full_path = folder / f'full-{background}.png'
            cropped_path = folder / f'crop-{background}.png'
            doc.export_image(full_path, OutputOptions('png', 'custom', max_edge, max_edge,
                                                      background=background))
            doc.export_image(cropped_path, OutputOptions('png', 'custom', max_edge, max_edge,
                                                         background=background, crop_margins=True))
            with Image.open(full_path) as full, Image.open(cropped_path) as cropped:
                bbox = image_ink_bbox(full) or (0, 0, full.width, full.height)
                if background == 'transparent':
                    transparent_bbox = bbox
                # Large opaque exports deliberately detect ink from a
                # transparent scan: hidden white-on-white geometry can enlarge
                # the conservative crop, while the opaque full-page bitmap
                # cannot reveal it. Both bounding boxes are valid only when
                # the cropped pixels equal the corresponding FULL-page ROI.
                candidates = [bbox]
                if transparent_bbox is not None and transparent_bbox != bbox:
                    candidates.append(transparent_bbox)
                matched_bbox = None
                for candidate in candidates:
                    expected = full.crop(candidate)
                    try:
                        if (cropped.mode == expected.mode and
                                cropped.size == expected.size and
                                cropped.tobytes() == expected.tobytes()):
                            matched_bbox = candidate
                            break
                    finally:
                        expected.close()
                output.append({'background': background, 'full_size': list(full.size),
                               'cropped_size': list(cropped.size),
                               'matched_full_page_bbox': list(matched_bbox) if matched_bbox else None,
                               'pixel_equal': matched_bbox is not None,
                               'full_sha256': sha256(full_path),
                               'cropped_sha256': sha256(cropped_path)})
    final_hash = sha256(source)
    result = {'source_pdf_name': source.name, 'source_sha256': initial_hash,
              'source_unchanged': initial_hash == final_hash,
              'page': page_number, 'page_count': all_pages, 'ocg_count': ocg_count,
              'layer_state': state, 'max_edge': max_edge, 'exports': output}
    result['pass'] = result['source_unchanged'] and all(x['pixel_equal'] for x in output)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Original OnMap PDF PNG crop P0 QA (local only).')
    parser.add_argument('pdf', type=Path, help='Original OnMap PDF; never modified.')
    parser.add_argument('--page', type=int, default=1, help='1-based page number (default 1).')
    parser.add_argument('--max-edge', type=int, default=1600, help='Max output edge in pixels; use 5000 for tiled path.')
    parser.add_argument('--layer-off', action='append', default=[], help='Exact PDF OCG layer name to disable; may repeat.')
    parser.add_argument('--out-dir', type=Path, help='Keep QA PNGs under a new unique subfolder here.')
    parser.add_argument('--report', type=Path, help='Optional JSON report path (no source PDF contents).')
    args = parser.parse_args(argv)
    try:
        if args.out_dir is None:
            workspace = tempfile.TemporaryDirectory(prefix='sunrise-onmap-p0-')
            context = workspace
        else:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            workspace = Path(tempfile.mkdtemp(prefix='sunrise-onmap-p0-', dir=args.out_dir))
            context = nullcontext(str(workspace))
        with context as location:
            result = validate(args.pdf, args.page, args.max_edge, args.layer_off, Path(location))
            if args.out_dir is not None:
                result['qa_images_dir'] = str(location)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            if args.report.exists():
                raise ValueError(f'Report already exists, no overwrite: {args.report}')
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['pass'] else 1
    except (OSError, ValueError, DrawingError, fitz.FileDataError) as exc:
        print(f'P0 validation error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
