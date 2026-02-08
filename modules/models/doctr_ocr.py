import re
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
from PIL import Image
import tempfile
import os

from .base import AIModel
from modules.data.receipt_data import ReceiptData, ItemData


class DoctrOCRModel(AIModel):
    def __init__(self):
        self.model = ocr_predictor(pretrained=True)

    def run(self, image) -> ReceiptData:
        if not isinstance(image, Image.Image):
            image = Image.open(image).convert("RGB")
        else:
            image = image.convert("RGB")

    
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image.save(tmp.name)
            image_path = tmp.name

    
        doc = DocumentFile.from_images(image_path)
        result = self.model(doc)

    
        try:
            os.remove(image_path)
        except Exception:
            pass

        lines = self._extract_lines(result)
        items, total = self._parse_receipt(lines)

        return ReceiptData(
            items={it.id: it for it in items},
            total=total
    )

    def _extract_lines(self, result):
        lines = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    text = " ".join([w.value for w in line.words])
                    if text.strip():
                        lines.append(text)
        return lines

    def _parse_receipt(self, lines):
        items = []
        total = 0.0

        i = 0
        while i < len(lines) - 2:
            name = lines[i].strip()
            qty = lines[i + 1].strip()
            price = lines[i + 2].strip()

            if name.lower() in ["sub total", "subtotal", "total"]:
                break

            if qty.isdigit():
                items.append(
                    ItemData(
                        name=name,
                        count=int(qty),
                        total_price=self._convert_price(price),
                    )
                )
                i += 3
                continue

            i += 1

        for idx, line in enumerate(lines):
            if line.strip().lower() == "total" and idx + 1 < len(lines):
                total = self._convert_price(lines[idx + 1])

        return items, total

    def _convert_price(self, text: str) -> float:
        cleaned = re.sub(r"[^\d]", "", text)
        return float(cleaned) if cleaned else 0.0