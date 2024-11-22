from io import BytesIO

import litserve as ls
import numpy as np
import torch
from fastapi import Response, UploadFile
from PIL import Image

from lang_sam import LangSAM
from lang_sam.utils import draw_image

PORT = 8000

import os
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
# fallback for macbook MPS issues with SAM2

class LangSAMAPI(ls.LitAPI):
    def setup(self, device: str) -> None:
        """Initialize or load the LangSAM model."""
        self.model = LangSAM(sam_type="sam2.1_hiera_small")
        print("LangSAM model initialized.")

    def decode_request(self, request) -> dict:
        """Decode the incoming request to extract parameters and image bytes.

        Assumes the request is sent as multipart/form-data with fields:
        - sam_type: str
        - box_threshold: float
        - text_threshold: float
        - text_prompt: str
        - image: UploadFile
        """
        # Extract form data
        sam_type = request.get("sam_type")
        box_threshold = float(request.get("box_threshold", 0.3))
        text_threshold = float(request.get("text_threshold", 0.25))
        text_prompt = request.get("text_prompt", "")

        # Extract image file
        image_file: UploadFile = request.get("image")
        if image_file is None:
            raise ValueError("No image file provided in the request.")

        image_bytes = image_file.file.read()

        return {
            "sam_type": sam_type,
            "box_threshold": box_threshold,
            "text_threshold": text_threshold,
            "image_bytes": image_bytes,
            "text_prompt": text_prompt,
        }

    def predict(self, inputs: dict) -> dict:
        """Perform prediction using the LangSAM model."""
        print("Starting prediction with parameters:")
        print(
            f"sam_type: {inputs['sam_type']}, \
                box_threshold: {inputs['box_threshold']}, \
                text_threshold: {inputs['text_threshold']}, \
                text_prompt: {inputs['text_prompt']}"
        )

        if inputs["sam_type"] != self.model.sam_type:
            print(f"Updating SAM model type to {inputs['sam_type']}")
            self.model.sam.build_model(inputs["sam_type"])

        try:
            image_pil = Image.open(BytesIO(inputs["image_bytes"])).convert("RGB")
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}")

        results = self.model.predict(
            images_pil=[image_pil],
            texts_prompt=[inputs["text_prompt"]],
            box_threshold=inputs["box_threshold"],
            text_threshold=inputs["text_threshold"],
        )

        results = results[0]
        boxes = results['boxes']
        if not isinstance(boxes, np.ndarray):
            # If it's not a numpy array, assume it's a torch tensor and convert to CPU
            if isinstance(boxes, torch.Tensor):
                boxes = boxes.cpu().numpy()
            else:
                raise TypeError("Unexpected type for boxes. Expected numpy array or torch tensor.")

        if not len(results["masks"]):
            print("No masks detected. Returning empty boxes.")
            return {"boxes": boxes}

        return {"boxes": boxes}

    def encode_response(self, output: dict) -> Response:
        """Encode the prediction result into an HTTP response."""
        try:
            boxes = output["boxes"]
            buffer = BytesIO()
            np.save(buffer, boxes)
            buffer.seek(0)

            return Response(content=buffer.getvalue(), media_type="application/octet-stream")
        except Exception as e:
            raise ValueError(f"Error encoding boxes: {e}")

lit_api = LangSAMAPI()
server = ls.LitServer(lit_api)


if __name__ == "__main__":
    print(f"Starting LitServe and Gradio server on port {PORT}...")
    server.run(port=PORT)
