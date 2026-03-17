import json
import anthropic
from app.config import get_settings

# ─── Base system prompts ──────────────────────────────────────────────────────

ASSESSMENT_SYSTEM_PROMPT_BASE = """\
You are an expert bicycle mechanic and identifier. When given photos of a bike,
you analyse and return a structured JSON assessment of its components.

{brand_reference_block}

Return ONLY valid JSON with this exact schema — no preamble, no markdown fences:
{{
  "make": "string or null",
  "model": "string or null",
  "year_estimate": "string or null",
  "frame": {{
    "material": "string",
    "condition": "good|fair|poor",
    "notes": "string"
  }},
  "components": {{
    "groupset":   {{"brand": "string", "model": "string", "condition": "good|fair|poor", "confidence": 0.0}},
    "wheels":     {{"brand": "string", "type": "string",  "condition": "good|fair|poor", "confidence": 0.0}},
    "brakes":     {{"type": "string",  "brand": "string", "condition": "good|fair|poor", "confidence": 0.0}},
    "handlebars": {{"type": "string",  "brand": "string", "condition": "good|fair|poor", "confidence": 0.0}},
    "saddle":     {{"brand": "string", "condition": "good|fair|poor", "confidence": 0.0}},
    "fork":       {{"material": "string", "brand": "string", "condition": "good|fair|poor", "confidence": 0.0}},
    "suspension": {{"type": "string",  "brand": "string", "condition": "good|fair|poor", "confidence": 0.0}}
  }},
  "overall_condition": "good|fair|poor",
  "assessment_notes": "string",
  "confidence_overall": 0.0
}}

Confidence values are 0.0-1.0. Use null for components not visible or not applicable.
"""

CHALLENGE_SYSTEM_PROMPT = """\
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


def run_assessment(base64_images: list, brand_entries: list = None) -> dict:
    client = get_claude_client()
    system_prompt = build_assessment_prompt(brand_entries or [])

    image_content = build_image_content(base64_images)
    image_content.append({
        "type": "text",
        "text": "Please assess this bike and return the JSON component breakdown.",
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": image_content}],
    )

    return json.loads(_strip_fences(response.content[0].text))


def run_challenge(base64_images: list, component_name: str, previous_assessment: dict) -> dict:
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
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=CHALLENGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": image_content}],
    )

    return json.loads(_strip_fences(response.content[0].text))
