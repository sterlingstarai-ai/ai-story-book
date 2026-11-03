"""Performance directions for a single AI narrator, shared by TTS adapters."""

STYLE_DIRECTIONS = {
    "natural": (
        "Tell the story like a skilled picture-book narrator: warm, clear, and conversational, "
        "with moderate changes in emphasis and natural pauses."
    ),
    "animated": (
        "Perform an engaging read-aloud for young children, with noticeably lively pitch, "
        "rhythm and emphasis that follow the emotions and actions in the text. "
        "Make quoted dialogue distinctly expressive from the narration, using playful character "
        "inflection when the words support it. Vary pacing naturally for surprise and excitement, "
        "while keeping every word clear and comfortable to listen to. Use one narrator voice; "
        "do not add dialogue, vocal effects, or imitate a known performer."
    ),
    "bedtime": (
        "Tell a soothing bedtime story: quiet, reassuring, evenly paced, with gentle inflection "
        "and soft pauses. Avoid sudden loudness or energetic character performance."
    ),
}
