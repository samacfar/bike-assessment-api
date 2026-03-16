import anthropic
from app.config import get_settings

ASSESSMENT_SYSTEM_PROMPT = """
You are an expert bicycle mechanic and identifier. When given photos of a bike,
you analyse and return a structured JSON assessment of its components.

Return ONLY valid JSON with this exact schema:
{
  "make": "string or null",
  "model": "string or null",
  "year_estimate": "string or null",
  "frame": {
    "material": "string",
    "condition": "good|fair|poor",
    "notes": "string"
  },
  "components": {
    "groupset": {"brand": "string", "model": "string", "condition": "good|fair|poor", "confidence": 0.0},
    "wheels": {"brand": "string", "type": "string", "condition": "good|fair|poor", "confidence": 0.0},
    "brakes": {"type": "string", "brand": "string", "condition": "good|fair|poor", "confidence": 0.0},
    "handlebars": {"type": "string", "brand": "string", "condition": "good|fair|poor", "confidence": 0.0},
    "saddle": {"brand": "string", "condition": "good|fair|poor", "confidence": 0.0},
    "fork": {"material": "string", "brand": "string", "condition": "good|fair|poor", "confidence": 0.0},
    "suspension": {"type": "string", "brand": "string", "condition": "good|fair|poor", "confidence": 0.0}
  },
  "overall_condition": "good|fair|poor",
  "assessment_notes": "string",
  "confidence_overall": 0.0
}

Confidence values are 0.0–1.0. Use null for components not visible or not applicable.
"""

CHALLENGE_SYSTEM_PROMPT = """
You are an expert bicycle mechanic. You are being asked to re-examine a specific
component assessment that has been flagged as potentially incorrect.

Re-analyse the provided photos focusing specifically on the flagged component.
Return ONLY valid JSON for that single component using this schema:
{
  "component": "string (component name)",
  "previous_assessment": {},
  "revised_assessment": {
    "brand": "string",
    "model": "string",
    "condition": "good|fair|poor",
    "confidence": 0.0,
    "notes": "string"
  },
  "reasoning": "string explaining what changed and why"
}
"""


def get_claude_client() -> anthropic.Anthropic:
    settings = get_settings()
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def build_image_content(base64_images: list[str]) -> list[dict]:
    """Convert list of base64 image strings into Anthropic content blocks."""
    content = []
    for img_b64 in base64_images:
        # Support optional data URI prefix stripping
        if "," in img_b64:
            img_b64 = img_b64.split(",", 1)[1]
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_b64,
            },
        })
    return content


def run_assessment(base64_images: list[str]) -> dict:
    """Send images to Claude Vision and return structured component JSON."""
    client = get_claude_client()
    image_content = build_image_content(base64_images)
    image_content.append({
        "type": "text",
        "text": "Please assess this bike and return the JSON component breakdown.",
    })

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=ASSESSMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": image_content}],
    )

    import json
    raw = response.content[0].text.strip()
    return json.loads(raw)


def run_challenge(
    base64_images: list[str],
    component_name: str,
    previous_assessment: dict,
) -> dict:
    """Re-run Claude on a specific component that has been challenged."""
    client = get_claude_client()
    image_content = build_image_content(base64_images)
    image_content.append({
        "type": "text",
        "text": (
            f"Please re-examine the '{component_name}' component specifically. "
            f"Previous assessment was: {previous_assessment}. "
            "Return the revised JSON assessment."
        ),
    })

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=CHALLENGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": image_content}],
    )

    import json
    raw = response.content[0].text.strip()
    return json.loads(raw)