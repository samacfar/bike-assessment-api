import json
import anthropic
from app.config import get_settings

# ─── Models ──────────────────────────────────────────────────────────────────
MODEL_SONNET = "claude-sonnet-4-20250514"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

# ─── System prompts ───────────────────────────────────────────────────────────

ASSESSMENT_SYSTEM_PROMPT_BASE = """\
You are an expert bicycle mechanic and identifier with deep knowledge of bike brands, \
models, components, and specifications.

You will be shown one or more photos of a bike. Your job is to identify and assess it \
as accurately as possible from visual evidence only. Never guess — if you cannot see \
something clearly, set it to null and reflect the uncertainty in your confidence score.

Identification order: brand first, then bike type, then colour, then model family, \
then generation/variant, then frame spec, then trim level, then year, then motor type \
(only after model and year are confirmed).

{brand_reference_block}

Return ONLY valid JSON with this exact schema — no preamble, no markdown fences, \
no commentary:
{{
  "make": "string or null",
  "type": "Road|Mountain|Gravel|Hybrid|BMX|eBike|Kids|Other|null",
  "colour": "string or null",
  "model_family": "string or null",
  "generation_variant": "string or null",
  "frame_spec": "string or null",
  "trim_level": "string or null",
  "year": "string or null",
  "electric": true|false|null,
  "frame_material": "Carbon|Aluminium|Steel|Titanium|Other|null",
  "condition": "good|fair|poor",
  "components": {{
    "cassette":         {{"brand": "string or null", "model": "string or null", "speeds": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "rear_derailleur":  {{"brand": "string or null", "model": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "shifters":         {{"brand": "string or null", "model": "string or null", "type": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "brakes":           {{"brand": "string or null", "model": "string or null", "type": "Disc|Rim|Hydraulic|Mechanical|null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "wheels_rims":      {{"brand": "string or null", "model": "string or null", "size": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "tyres":            {{"brand": "string or null", "model": "string or null", "size": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "handlebars":       {{"brand": "string or null", "model": "string or null", "type": "Drop|Flat|Riser|Other|null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "saddle":           {{"brand": "string or null", "model": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}},
    "fork":             {{"brand": "string or null", "model": "string or null", "type": "Rigid|Suspension|null", "material": "Carbon|Aluminium|Steel|null", "travel_mm": "string or null", "condition": "good|fair|poor|null", "confidence": 0.0}}
  }},
  "assessment_notes": "string",
  "confidence_overall": 0.0
}}

Rules:
- Confidence values are 0.0-1.0. Use null for any component not visible or not applicable.
- Set electric to true only if motor, battery, or eBike branding is visible.
- If brand cannot be confirmed visually, set make to null — do not guess.
- assessment_notes should explain any uncertainty or notable observations.
"""

CHALLENGE_SYSTEM_PROMPT = """\
You are an expert bicycle mechanic. A specific component assessment has been flagged \
as potentially incorrect. Re-examine the photos focusing only on the flagged component.

Return ONLY valid JSON using this schema — no preamble, no markdown fences:
{
  "component": "string",
  "previous_assessment": {},
  "revised_assessment": {
    "brand": "string or null",
    "model": "string or null",
    "condition": "good|fair|poor|null",
    "confidence": 0.0,
    "notes": "string"
  },
  "reasoning": "string explaining what changed and why, or why the original was correct"
}
"""

# ─── Brand reference block builder ───────────────────────────────────────────

def build_brand_reference_block(brand_entries: list) -> str:
    if not brand_entries:
        return ""
    lines = [
        "## Brand Visual Reference",
        "",
        "Use the following verified brand fingerprints to aid identification.",
        "These are confirmed visual signatures — prioritise them over general knowledge.",
        "",
    ]
    for entry in brand_entries:
        brand = entry.get("brand", "Unknown")
        lines.append(f"### {brand}")
        for s in entry.get("logo_shapes", []):
            lines.append(f"  LOGO: {s}")
        for s in entry.get("frame_signatures", []):
            lines.append(f"  FRAME: {s}")
        for c in entry.get("distinctive_colours", []):
            lines.append(f"  COLOUR: {c}")
        for fam in entry.get("model_family_identifiers", []):
            fname = fam.get("family", "")
            ids = "; ".join(fam.get("identifiers", []))
            lines.append(f"  MODEL FAMILY {fname}: {ids}")
        lines.append("")
    return "\n".join(lines)


def build_assessment_prompt(brand_entries: list) -> str:
    block = build_brand_reference_block(brand_entries)
    return ASSESSMENT_SYSTEM_PROMPT_BASE.format(brand_reference_block=block)


# ─── Claude client ────────────────────────────────────────────────────────────

def get_claude_client():
    settings = get_settings()
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def build_image_content(base64_images: list) -> list:
    content = []
    for img_b64 in base64_images:
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


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def run_assessment(base64_images: list, brand_entries: list = None) -> tuple[dict, str]:
    """
    Run bike assessment. Returns (assessment_dict, model_name_used).
    Currently uses Sonnet for all calls.
    Haiku/Sonnet split will be implemented once baseline accuracy data
    is collected across 100 assessments.
    """
    client = get_claude_client()
    system_prompt = build_assessment_prompt(brand_entries or [])

    image_content = build_image_content(base64_images)
    image_content.append({
        "type": "text",
        "text": "Please assess this bike and return the JSON breakdown.",
    })

    response = client.messages.create(
        model=MODEL_SONNET,
        max_tokens=1200,
        system=system_prompt,
        messages=[{"role": "user", "content": image_content}],
    )

    assessment = json.loads(_strip_fences(response.content[0].text))
    return assessment, MODEL_SONNET


def run_challenge(base64_images: list, component_name: str, previous_assessment: dict) -> dict:
    """
    Re-run Claude on a specific component that has been challenged.
    Max 2 images — caller should pass only the most relevant image(s).
    """
    client = get_claude_client()
    images = base64_images[:2]
    image_content = build_image_content(images)
    image_content.append({
        "type": "text",
        "text": (
            f"Please re-examine the '{component_name}' component specifically. "
            f"Previous assessment was: {previous_assessment}. "
            "Return the revised JSON assessment."
        ),
    })

    response = client.messages.create(
        model=MODEL_SONNET,
        max_tokens=500,
        system=CHALLENGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": image_content}],
    )

    return json.loads(_strip_fences(response.content[0].text))
