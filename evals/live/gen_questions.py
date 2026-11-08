# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportOptionalMemberAccess=false, reportGeneralTypeIssues=false
"""Generate the scripted question WAVs (16 kHz mono) used by the live eval client."""

import asyncio
import subprocess
from pathlib import Path

import edge_tts  # type: ignore[import-not-found]

QUESTIONS = {
    "q01": "What is the purpose of this project?",
    "q02": "What are the main use cases?",
    "q03": "How does the system work technically?",
    "q04": "Who are the competitors?",
    "q05": "What are the cons or limitations?",
    "q06": "Which languages are supported?",
    "q07": "How much does a call cost?",
    "q08": "How do you handle privacy?",
    "q09": "What technology stack do you use?",
    "q10": "How do you evaluate quality?",
    "q11": "What makes this design distinctive?",
    "q12": "How does the agent search company knowledge?",
    "q13": "What happens when the service is overloaded?",
    "q14": "What's the weather like today?",
    "q15": "Can I see the dogs for this project?",
}
EXTRA = {
    "interrupt": "Stop, wait — actually, what does a call cost?",
    "stop": "Stop.",
}

OUT = Path(__file__).parent / "data"


async def synth(name: str, text: str) -> None:
    raw = OUT / f"{name}.raw.wav"
    await edge_tts.Communicate(text, voice="en-US-AriaNeural", rate="+10%").save(str(raw))
    subprocess.run(  # noqa: S603, ASYNC221
        [
            "/usr/bin/ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(OUT / f"{name}.wav"),
        ],
        check=True,
    )
    raw.unlink()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in {**QUESTIONS, **EXTRA}.items():
        await synth(name, text)
        print("wrote", OUT / f"{name}.wav")


if __name__ == "__main__":
    asyncio.run(main())
