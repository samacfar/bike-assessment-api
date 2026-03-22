import anthropic
from app.config import get_settings

# ── System prompt ─────────────────────────────────────────────────────────────
# Proven approach from proof of concept. Single call, Sonnet, image always sent.
# Identification order: brand → type → colour → model family → generation →
# frame spec → trim → year → motor. Visual evidence only, no guessing.

SYSTEM_PROMPT = """You are an expert bicycle identification specialist. Analyse the photo carefully.

IDENTIFICATION ORDER — work through each step before answering:
1. HEAD TUBE — read brand name, badge, or logo
2. FRAME SHAPE + TYRES — determine bike type (MTB / Road / Gravel / eMTB etc)
3. FRAME COLOUR — note primary and secondary colours
4. TUBE JUNCTIONS — weld beads visible = metal frame (Aluminium or Steel), not Carbon
5. DOWN TUBE — model family name, generation callout (e.g. EVO, SL, VLT), any text near BB end
6. TOP TUBE + SEAT TUBE — model name, trim level, size marking
7. YEAR — deduce from components or frame details if possible
8. BOTTOM BRACKET AREA — motor unit present? Read brand if visible. Check AFTER model confirmed.
9. COMPONENTS — read derailleur, brakes, fork, tyre sidewalls, rim branding

COLOUR ANOMALY CHECK — for each frame section:
- Any area where colour differs from surrounding paint may be text in a near-matching colour
- Examine carefully — mentally rotate to see if it resolves into letters or a logo

Return your assessment in EXACTLY this format. No extra text. No preamble. No markdown.

IMAGE QUALITY
Quality Flag: [OK / POOR - reason]

BIKE OVERVIEW
Make/Brand: [brand name as written on frame, or Unknown]
Type: [eMTB / eRoad / eBike / MTB / Road / Gravel / Hybrid / BMX / Other]
Colour: [primary colour(s) of frame as seen in photo]
Model Family: [primary model name e.g. Sight, Stumpjumper, Fuel EX, or Unknown]
Generation/Variant: [sub-model or generation e.g. VLT, EVO, SL, or Unknown]
Frame Spec: [material callout on frame e.g. Carbon, Alloy, or Unknown]
Trim Level: [spec tier as badged e.g. C1, C2, Comp, Expert, S-Works, or Unknown]
Year (approx): [year or range, or Unknown]
Electric: [Yes - motor brand/type if visible / No / Unknown]
Frame Material: [Carbon / Aluminium / Steel / Titanium / Unknown — weld beads confirm metal]
Condition: [Excellent / Good / Fair / Poor]

COMPONENTS
Cassette: [speeds and brand e.g. Shimano 12-speed 10-51t, or Unknown] | Confidence: [High/Medium/Low]
Rear Derailleur: [brand and model e.g. Shimano SLX RD-M7100, or Unknown] | Confidence: [High/Medium/Low]
Shifters: [brand and model, or Unknown] | Confidence: [High/Medium/Low]
Brakes: [type and brand e.g. Shimano hydraulic disc, or Unknown] | Confidence: [High/Medium/Low]
Wheels/Rims: [brand or description, or Unknown] | Confidence: [High/Medium/Low]
Tyres: [brand and model if visible e.g. Maxxis Minion DHF 2.5, or Unknown] | Confidence: [High/Medium/Low]
Handlebars: [type and approx width, or Unknown] | Confidence: [High/Medium/Low]
Saddle: [brand if visible, or Unknown] | Confidence: [High/Medium/Low]
Fork: [brand and model if visible e.g. RockShox Pike, or Unknown] | Confidence: [High/Medium/Low]

ESTIMATED VALUE RANGE
New RRP (approx): NZ$[X] - NZ$[Y]
Current Market Value: NZ$[X] - NZ$[Y]
Confidence in Value: [High/Medium/Low]"""


def run_assessment(base64_image: str) -> str:
    """Single Sonnet call with image. Returns raw text response."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64_image,
                    }
                },
                {
                    "type": "text",
                    "text": "Please assess this bike."
                }
            ]
        }]
    )

    return response.content[0].text


def run_challenge(base64_image: str, field: str, confirmed_facts: str, note: str) -> str:
    """Resolve a specific field using web search + confirmed facts.
    If a note is provided, skip the image — web search is faster and sufficient.
    If no note, include the image for visual re-examination.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    use_image = not note.strip()  # Only send image if no note given

    user_msg = (
        f"Confirmed facts about this bike: {confirmed_facts}\n\n"
        f"Field to resolve: {field}\n"
    )
    if note:
        user_msg += f"User note: {note}\n\n"
        user_msg += (
            f"Search the web using the confirmed facts and user note to find the correct value "
            f"for '{field}'. Use a short direct search query e.g. 'Norco Sight VLT red trim level'.\n\n"
        )
    else:
        user_msg += (
            f"Look carefully at the image to identify '{field}'. "
            f"If not visible, use web search with the confirmed facts.\n\n"
        )
    user_msg += (
        f"Reply with ONLY this single line, nothing else:\n"
        f"{field}: [value] | Confidence: [High/Medium/Low]"
    )

    content = []
    if use_image:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64_image,
            }
        })
    content.append({"type": "text", "text": user_msg})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system="You are a bicycle identification specialist. Answer with only the requested field value in the specified format.",
        messages=[{"role": "user", "content": content}]
    )

    # Extract text from response (may include tool_use blocks from web search)
    return " ".join(
        block.text for block in response.content
        if hasattr(block, "text") and block.text
    ).strip()
