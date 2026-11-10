"""Stage 1: layout detection + reading order with PP-DocLayoutV3 (Apache-2.0).

The model returns regions already in reading order (single forward pass), each with a label such as
text / table / formula / header / footer / number (page number) / aside_text.
"""

from dataclasses import dataclass

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection

MODEL_ID = "PaddlePaddle/PP-DocLayoutV3_safetensors"

# Regions olmOCR-Bench (and most downstream uses) want removed from the linearised text.
DROP_LABELS = {"header", "footer", "number", "aside_text"}


@dataclass
class Region:
    order: int
    label: str
    score: float
    box: tuple  # x0, y0, x1, y1 in image pixels


class LayoutModel:
    def __init__(self, device: str | None = None, threshold: float = 0.4):
        self.device = device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
        self.processor = AutoImageProcessor.from_pretrained(MODEL_ID)
        self.model = AutoModelForObjectDetection.from_pretrained(MODEL_ID).to(self.device).eval()
        self.threshold = threshold

    @torch.inference_mode()
    def __call__(self, images: list[Image.Image]) -> list[list[Region]]:
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        outputs = self.model(**inputs)
        sizes = [im.size[::-1] for im in images]
        results = self.processor.post_process_object_detection(outputs, threshold=self.threshold, target_sizes=sizes)
        pages = []
        for res in results:
            regions = []
            for i, (score, label, box) in enumerate(zip(res["scores"], res["labels"], res["boxes"])):
                regions.append(Region(i, self.model.config.id2label[label.item()], round(score.item(), 3),
                                      tuple(round(v, 1) for v in box.tolist())))
            pages.append(regions)
        return pages
