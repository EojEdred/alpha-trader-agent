from fastapi import APIRouter
from pydantic import BaseModel
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

router = APIRouter()

class LiquidRequest(BaseModel):
    prompt: str
    max_tokens: int = 100
    temperature: float = 0.7
    top_p: float = 0.9

@router.post("/lfm-2b")
async def generate_liquid(req: LiquidRequest):
    """
    LFM-3B inference endpoint using transformers.
    """
    try:
        # Load model and tokenizer (in production, these should be cached)
        model_name = "Liquid-AI/Liquid-3B-OpenLm"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            device_map="auto"
        )

        # Encode the prompt
        inputs = tokenizer.encode(req.prompt, return_tensors="pt").to(model.device)

        # Generate response
        with torch.no_grad():
            outputs = model.generate(
                inputs,
                max_new_tokens=req.max_tokens,
                temperature=req.temperature,
                top_p=req.top_p,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id
            )

        # Decode the output
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Extract only the generated part (remove the original prompt)
        if req.prompt in generated_text:
            response_text = generated_text[len(req.prompt):].strip()
        else:
            response_text = generated_text.strip()

        return {
            "status": "success",
            "text": response_text,
            "model": "lfm-3b",
            "input_tokens": len(inputs[0]),
            "output_tokens": len(outputs[0]) - len(inputs[0])
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error during generation: {str(e)}",
            "text": ""
        }
