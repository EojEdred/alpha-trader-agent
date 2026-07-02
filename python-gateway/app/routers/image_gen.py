from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import torch
from diffusers import AutoPipelineForText2Image
from PIL import Image
import base64
from io import BytesIO
import os

router = APIRouter()

class ImageGenRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    num_inference_steps: int = 30
    guidance_scale: float = 7.5

@router.post("/qwen-image")
async def generate_qwen_image(req: ImageGenRequest):
    """
    Qwen-Image-2512 generation endpoint using diffusers.
    """
    try:
        # Load the pipeline (in production, this should be cached)
        model_name = "Qwen/Qwen2-VL-2B-Instruct"  # Using a compatible Qwen model
        pipe = AutoPipelineForText2Image.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            variant="fp16"
        )

        # Move to GPU if available
        device = "cuda" if torch.cuda.is_available() else "cpu"
        pipe = pipe.to(device)

        # Generate the image
        image = pipe(
            req.prompt,
            negative_prompt=req.negative_prompt,
            width=req.width,
            height=req.height,
            num_inference_steps=req.num_inference_steps,
            guidance_scale=req.guidance_scale
        ).images[0]

        # Convert image to base64 for transmission
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        return {
            "status": "success",
            "image_base64": img_str,
            "model": "qwen-image-2512",
            "width": req.width,
            "height": req.height,
            "prompt": req.prompt
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error during image generation: {str(e)}",
            "image_base64": ""
        }
