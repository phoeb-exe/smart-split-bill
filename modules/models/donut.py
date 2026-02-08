import torch
import xmltodict
import re
from PIL import Image
from transformers import AutoModelForVision2Seq, AutoProcessor

from modules.data.receipt_data import ItemData, ReceiptData

from .base import AIModel

MODEL_NAME = "naver-clova-ix/donut-base-finetuned-cord-v2"

def _fix_unclosed_tags(xml_str):
        opened = re.findall(r"<([a-zA-Z_]+)>", xml_str)
        closed = re.findall(r"</([a-zA-Z_]+)>", xml_str)

        for tag in reversed(opened):
            if opened.count(tag) > closed.count(tag):
                xml_str += f"</{tag}>"

        return xml_str

class DonutModel(AIModel):

    def __init__(self):
        self.processor = AutoProcessor.from_pretrained(MODEL_NAME)
        self.model = AutoModelForVision2Seq.from_pretrained(MODEL_NAME)

    def run(self, image):
        decoder_input_ids, pixel_values = self._preprocess(image)
        generation_output = self._inference(decoder_input_ids, pixel_values)
        receipt_dict = self._postprocessing(generation_output)
        return self._formatting(receipt_dict)

    def _preprocess(self, image): 
        decoder_input_ids = self.processor.tokenizer(
            "<s_cord-v2>", add_special_tokens=False
        ).input_ids
        decoder_input_ids = torch.tensor(decoder_input_ids).unsqueeze(0)
        pixel_values = self.processor(image, return_tensors="pt").pixel_values
        return decoder_input_ids, pixel_values

    def _inference(self, decoder_input_ids, pixel_values): 
        generation_output = self.model.generate(
            pixel_values,
            decoder_input_ids=decoder_input_ids,
            max_length=self.model.decoder.config.max_position_embeddings,
            pad_token_id=self.processor.tokenizer.pad_token_id,
            eos_token_id=self.processor.tokenizer.eos_token_id,
            use_cache=True,
            num_beams=1,
            bad_words_ids=[[self.processor.tokenizer.unk_token_id]],
            return_dict_in_generate=True,
        )
        return generation_output

    def _postprocessing(self, generation_output):
        decoded_sequence = self.processor.batch_decode(
            generation_output.sequences
        )[0]

        decoded_sequence = decoded_sequence.replace(
            self.processor.tokenizer.eos_token, ""
        )
        decoded_sequence = decoded_sequence.replace(
            self.processor.tokenizer.pad_token, ""
        )

        start = decoded_sequence.find("<")
        end = decoded_sequence.rfind(">") + 1
        if start != -1 and end != -1:
            decoded_sequence = decoded_sequence[start:end]

        decoded_sequence += "</s_cord-v2>"
        decoded_sequence = f"<root>{decoded_sequence}</root>"
        decoded_sequence = _fix_unclosed_tags(decoded_sequence)

        try:
            dict_ = xmltodict.parse(decoded_sequence)
        except Exception:
            dict_ = {"raw_output": decoded_sequence}

        return dict_

    def _formatting(self, receipt_dict: dict) -> ReceiptData:
        """Parse dictionary data of model predictions.

        Args:
            receipt_dict (dict): prediction dictionary

        Returns:
            ReceiptData: parsed receipt data
        """
        if "root" in receipt_dict:
            data_dict = receipt_dict["root"].get("s_cord-v2", {})
        else:
            data_dict = receipt_dict.get("s_cord-v2", {})

        menu_dict = data_dict.get("s_menu", {})

        item_names = menu_dict.get("s_nm", [])
        item_counts = menu_dict.get("s_cnt", [])
        item_prices = menu_dict.get("s_price", [])

        if isinstance(item_names, str):
            item_names = [item_names]
        if isinstance(item_counts, str):
            item_counts = [item_counts]
        if isinstance(item_prices, str):
            item_prices = [item_prices]

        items = []
        for name, count, price in zip(item_names, item_counts, item_prices):
            try:
                items.append(
                    ItemData(
                        name=name,
                        count=int(count),
                        total_price=_convert_price_str_to_float(price),
                    )
                )
            except Exception:
                continue

        total_dict = data_dict.get("s_total", {})
        total_price_str = total_dict.get("s_total_price", "0")
        total = _convert_price_str_to_float(total_price_str)

        return ReceiptData(
            items={it.id: it for it in items},
            total=total,
        )


def _convert_price_str_to_float(price_str: str) -> float:
    """Convert price formatted as text to float.

    In particular, handle the price separator

    Args:
        price_str (str): price as text

    Returns:
        float: parsed float price
    """
    return float(price_str.replace(",", ""))
