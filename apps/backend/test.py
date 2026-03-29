import asyncio
from google import genai

from src.truefit_infra.config import AppConfig

api_key = AppConfig.GEMINI_API_KEY
print("\n", api_key, "\n")
client = genai.Client(api_key=api_key)

model = "gemini-2.5-flash-native-audio-preview-12-2025"
config = {"response_modalities": ["AUDIO"], "output_audio_transcription": {}}


async def main():
    async with client.aio.live.connect(model=model, config=config) as session:
        print("Session started")

        # Send text and signal end of turn
        await session.send_client_content(
            turns=[{"role": "user", "parts": [{"text": "Hello, how are you?"}]}],
            turn_complete=True,  # This tells the model to respond
        )

        print("Waiting for responses...")

        async for response in session.receive():
            content = response.server_content
            if content:
                # Audio data (PCM bytes)
                if content.model_turn:
                    for part in content.model_turn.parts:
                        if part.inline_data:
                            print(
                                f"Audio chunk received: {len(part.inline_data.data)} bytes"
                            )

                if content.output_transcription:
                    print(f"Gemini: {content.output_transcription.text}")

                if content.turn_complete:
                    print("Turn complete")
                    break


if __name__ == "__main__":
    asyncio.run(main())
