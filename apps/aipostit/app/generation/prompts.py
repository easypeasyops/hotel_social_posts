from string import Template

SYSTEM_PROMPT = """\
You are a professional social media content writer for luxury and boutique hotels in Türkiye.
You write engaging, authentic posts in Turkish that appeal to both domestic and international guests.
Your tone is warm, evocative, and aspirational — never generic or salesy.
Always write in Turkish. The translation service will handle other languages.
"""  # noqa: E501

POST_TEMPLATE = Template("""\
Create $count social media post(s) for the following hotel.

## Hotel Profile
- Name: $hotel_name
- Location: $location
- Description: $description
- Target channels: $channels

## Available Assets
$asset_list

## Instructions
- Write exactly $count post(s), one per channel if multiple channels are listed
- Each post should highlight the hotel's unique character and the specific assets available
- Include 3-5 relevant hashtags in Turkish at the end of each post
- Keep each post under 2200 characters (Instagram limit)
- Season/context: $season

## Response Format
Return a JSON array with this exact structure:
[
  {
    "channel": "instagram",
    "body": "post text here with #hashtags"
  }
]
Return only the JSON array, no other text.
""")


def build_generation_prompt(hotel: dict, assets: list[dict], channels: list[str]) -> str:
    import datetime

    month = datetime.date.today().month  # noqa: DTZ011
    season = (
        "Spring (March–May)"
        if 3 <= month <= 5
        else "Summer (June–August)"
        if 6 <= month <= 8
        else "Autumn (September–November)"
        if 9 <= month <= 11
        else "Winter (December–February)"
    )

    asset_list = (
        "\n".join(
            f"- {a['category'].capitalize()}: {a['filename']} (ID: {a['id']})" for a in assets
        )
        or "No assets uploaded yet — write based on hotel description only."
    )

    return POST_TEMPLATE.substitute(
        count=len(channels),
        hotel_name=hotel["name"],
        location=hotel["location"],
        description=hotel.get("description") or "A beautiful hotel in Türkiye.",
        channels=", ".join(channels),
        asset_list=asset_list,
        season=season,
    )
