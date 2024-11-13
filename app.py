 # import logging
# import os

# from dotenv import load_dotenv
# from fastapi import FastAPI

# from vocode.streaming.agent.chat_gpt_agent import ChatGPTAgent
# from vocode.streaming.client_backend.conversation import ConversationRouter
# from vocode.streaming.models.agent import ChatGPTAgentConfig
# from vocode.streaming.models.message import BaseMessage
# from vocode.streaming.models.synthesizer import ElevenLabsSynthesizerConfig
# from vocode.streaming.models.transcriber import DeepgramTranscriberConfig, TimeEndpointingConfig
# from vocode.streaming.synthesizer.eleven_labs_websocket_synthesizer import ElevenLabsSynthesizer
# from vocode.streaming.transcriber.deepgram_transcriber import DeepgramTranscriber
# from vocode.streaming.vector_db.factory import VectorDBFactory
# from vocode.streaming.vector_db.pinecone import PineconeConfig

# load_dotenv()

# app = FastAPI(docs_url=None)

# logging.basicConfig()
# logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# # Ensure that the environment variable 'PINECONE_INDEX_NAME' is not None
# pinecone_index_name = os.getenv("PINECONE_INDEX_NAME")
# if pinecone_index_name is None:
#     raise ValueError("Environment variable 'PINECONE_INDEX_NAME' is not set.")

# vector_db_config = PineconeConfig(index=pinecone_index_name)

# INITIAL_MESSAGE = "Hello!"
# PROMPT_PREAMBLE = """
# I want you to act as an IT Architect. 
# I will provide some details about the functionality of an application or other 
# digital product, and it will be your job to come up with ways to integrate it 
# into the IT landscape. This could involve analyzing business requirements, 
# performing a gap analysis, and mapping the functionality of the new system to 
# the existing IT landscape. The next steps are to create a solution design. 

# You are an expert in these technologies: 
# - Langchain
# - Supabase
# - Next.js
# - Fastapi
# - Vocode.
# """

# TIME_ENDPOINTING_CONFIG = TimeEndpointingConfig()
# TIME_ENDPOINTING_CONFIG.time_cutoff_seconds = 2

# El_SYNTHESIZER_THUNK = lambda output_audio_config: ElevenLabsSynthesizer(
#     ElevenLabsSynthesizerConfig.from_output_audio_config(
#         output_audio_config,
#     ),
#     logger=logger,
# )

# DEEPGRAM_TRANSCRIBER_THUNK = lambda input_audio_config: DeepgramTranscriber(
#     DeepgramTranscriberConfig.from_input_audio_config(
#         input_audio_config=input_audio_config,
#         endpointing_config=TIME_ENDPOINTING_CONFIG,
#         min_interrupt_confidence=0.9,
#     ),
#     logger=logger,
# )

# conversation_router = ConversationRouter(
#     agent_thunk=lambda: ChatGPTAgent(
#         ChatGPTAgentConfig(
#             initial_message=BaseMessage(text=INITIAL_MESSAGE),
#             prompt_preamble=PROMPT_PREAMBLE,
#             vector_db_config=vector_db_config,
#         ),
#         logger=logger,
#     ),
#     synthesizer_thunk=El_SYNTHESIZER_THUNK,
#     transcriber_thunk=DEEPGRAM_TRANSCRIBER_THUNK,
#     logger=logger,
# )

# app.include_router(conversation_router.get_router())



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
from vocode.streaming.transcriber.deepgram_transcriber import DeepgramTranscriber

app = FastAPI()

class Settings(BaseSettings):
    openai_api_key: str = "your_openai_api_key"
    eleven_labs_api_key: str = "your_eleven_labs_api_key"
    deepgram_api_key: str = "your_deepgram_api_key"
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

async def process_audio(audio_data: bytes) -> bytes:
    # Set up audio processing components
    microphone_input, speaker_output = create_streaming_microphone_input_and_speaker_output(
        use_default_devices=False,
        use_blocking_speaker_output=True,
    )
    
    # Initialize conversation settings
    conversation = StreamingConversation(
        output_device=speaker_output,
        transcriber=DeepgramTranscriber(
            DeepgramTranscriberConfig(
                microphone_input,
                endpointing_config=PunctuationEndpointingConfig(),
                api_key=settings.deepgram_api_key
            ),
        ),
        agent=ChatGPTAgent(
            ChatGPTAgentConfig(
                openai_api_key=settings.openai_api_key,
                initial_message="How can I assist you today?",
                prompt_preamble="This is a friendly conversation."
            )
        ),
        synthesizer=ElevenLabsSynthesizer(
            ElevenLabsSynthesizerConfig.from_output_device(speaker_output),
            api_key=settings.eleven_labs_api_key
        ),
    )
    await conversation.start()
    
    # Process incoming audio
    conversation.receive_audio(audio_data)
    
    # Assume synthesized response is generated
    response_audio = await speaker_output.get_audio()  # Replace with actual audio retrieval logic
    await conversation.terminate()
    
    return response_audio
# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            audio_data = await websocket.receive_bytes()  # Receive audio bytes from client

            # Transcribe audio, generate response, and synthesize it
            transcribed_text = await conversation_router.transcriber.transcribe(audio_data)
            print("transcribed text :",transcribed_text)
            if transcribed_text:
                response = await conversation_router.agent.respond(transcribed_text)
                synthesized_audio = await conversation_router.synthesizer.synthesize(response)
                
                # Send synthesized audio back to client
                await websocket.send_bytes(synthesized_audio)
    except WebSocketDisconnect:
        print("Client disconnected")
