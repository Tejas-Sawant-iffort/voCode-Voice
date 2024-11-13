 
import asyncio

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic_settings import BaseSettings, SettingsConfigDict

from vocode.helpers import create_streaming_microphone_input_and_speaker_output
from vocode.streaming.agent.chat_gpt_agent import ChatGPTAgent
from vocode.streaming.models.agent import ChatGPTAgentConfig
from vocode.streaming.models.synthesizer import ElevenLabsSynthesizerConfig
from vocode.streaming.models.transcriber import (
    DeepgramTranscriberConfig,
    PunctuationEndpointingConfig,
)
from vocode.streaming.streaming_conversation import StreamingConversation
from vocode.streaming.synthesizer.eleven_labs_synthesizer import ElevenLabsSynthesizer
from vocode.streaming.transcriber.deepgram_transcriber import DeepgramTranscriber

app = FastAPI()

# Replace these with actual API keys or load from environment variables
OPENAI_GPT_4_O_MODEL_NAME = "gpt-4"  # Update with your specific model
ELEVEN_LABS_ADAM_VOICE_ID = "your_voice_id_here"  # Replace with actual voice ID

class Settings(BaseSettings):
    openai_api_key: str = " "
    eleven_labs_api_key: str = " "
    deepgram_api_key: str = " "
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_audio(self, audio_chunk: bytes):
        for connection in self.active_connections:
            await connection.send_bytes(audio_chunk)

manager = ConnectionManager()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conversation = None
    try:
        # Set up audio input and output with default devices
        microphone_input, speaker_output = create_streaming_microphone_input_and_speaker_output(
            use_default_devices=True
        )
        
        # Create a new StreamingConversation instance for each WebSocket connection
        conversation = StreamingConversation(
            output_device=speaker_output,
            transcriber=DeepgramTranscriber(
                DeepgramTranscriberConfig(
                    chunk_size=100,
                    sampling_rate = 16000,
                    audio_encoding="linear16",
                    endpointing_config=PunctuationEndpointingConfig(),
                
         
                    api_key=settings.deepgram_api_key,
                ),
            ),
            agent=ChatGPTAgent(
                ChatGPTAgentConfig(
                    openai_api_key=settings.openai_api_key,
                    model_name=OPENAI_GPT_4_O_MODEL_NAME,
                    prompt_preamble="This is a friendly conversation."
                )
            ),
            synthesizer=ElevenLabsSynthesizer(
                ElevenLabsSynthesizerConfig(api_key=settings.eleven_labs_api_key,chunk_size=100,
                    sampling_rate = 16000,
                    audio_encoding="linear16",),
            ),
        )
        
        await conversation.start()

        while True:
            # Receive audio bytes from client
            audio_data = await websocket.receive_bytes()
            
            # Transcribe audio data to text
            transcribed_text = await StreamingConversation.transcriber.transcribe(audio_data)
            print("Transcribed text:", transcribed_text)
            
            if transcribed_text:
                # Generate response from the agent
                response = await conversation.agent.respond(transcribed_text)
                
                # Synthesize the response text to audio
                synthesized_audio = await conversation.synthesizer.synthesize(response)
                
                # Send synthesized audio back to client
                await websocket.send_bytes(synthesized_audio)
                
    except WebSocketDisconnect:
        print("Client disconnected")
    finally:
        # Terminate the conversation if it was successfully created
        if conversation:
            await conversation.terminate()
