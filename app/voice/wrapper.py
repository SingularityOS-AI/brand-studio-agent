"""
========================================================================================
BRAND STUDIO AGENT — ASSEMBLYAI VOICE WRAPPER
========================================================================================
Wrapper unificado y desacoplado para AssemblyAI:
1. Streaming STT v3 (Universal-3.5 Pro Realtime con word-level timestamps).
2. Voice Agent API WebSocket (Turn-taking, VAD, Tool Calling JSON-Schema).
3. Audio Intelligence: Detector de silencios acústicos (>350ms) y formateador de subtítulos.
4. Compatibilidad Híbrida: Permite conectar LLM propio (DeepSeek/Gemini) y TTS (ElevenLabs).
========================================================================================
"""

import os
import sys
import json
import asyncio
import time
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass

# Safe UTF-8 encoding for Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from assemblyai.streaming.v3 import (
        StreamingClient,
        StreamingClientOptions,
        StreamingParameters,
        StreamingEvents,
        TurnEvent,
        Word,
    )
except ImportError:
    StreamingClient = None
    StreamingClientOptions = None
    StreamingParameters = None
    StreamingEvents = None
    TurnEvent = None
    Word = None


@dataclass
class WordTimestamp:
    word: str
    start_ms: int
    end_ms: int
    confidence: float


class AssemblyAISpeechEngine:
    """
    Motor Soberano de Transcripción e Inteligencia Acústica en Tiempo Real.
    Usa el modelo Universal-3.5 Pro de AssemblyAI.
    """

    def __init__(self, api_key: Optional[str] = None):
        from app.config import settings
        self.api_key = api_key or settings.assemblyai_api_key
        if not self.api_key:
            print("[AVISO] ASSEMBLYAI_API_KEY no configurada. Configure su variable de entorno.")

        self.client: Optional[StreamingClient] = None
        self.accumulated_words: List[WordTimestamp] = []
        self.is_connected = False
        self.on_final_callback: Optional[Callable[[str, List[WordTimestamp]], None]] = None
        self.on_partial_callback: Optional[Callable[[str], None]] = None

    def start_realtime_transcription(
        self,
        on_final_callback: Callable[[str, List[WordTimestamp]], None],
        on_partial_callback: Optional[Callable[[str], None]] = None,
        sample_rate: int = 16000,
    ):
        """
        Inicia transcripción en tiempo real con detección de fin de turno y palabras.

        Args:
            on_final_callback: Callback cuando un turno termina completamente (end_of_turn=True)
            on_partial_callback: Callback con actualización parcial (end_of_turn=False)
            sample_rate: Tasa de muestreo del audio en Hz (por defecto 16000)
        """
        if not StreamingClient:
            raise RuntimeError("El paquete 'assemblyai' no está instalado. Ejecute: pip install assemblyai")

        self.on_final_callback = on_final_callback
        self.on_partial_callback = on_partial_callback

        def handle_turn(client: StreamingClient, event: TurnEvent):
            """
            Handler para eventos Turn de StreamingClient.
            event.end_of_turn determina si es parcial o final.
            """
            if event.words:
                for w in event.words:
                    self.accumulated_words.append(
                        WordTimestamp(
                            word=w.text,
                            start_ms=w.start,  # Word ya está en milisegundos
                            end_ms=w.end,
                            confidence=getattr(w, "confidence", 1.0),
                        )
                    )

            # end_of_turn == False → es un parcial (emisión en curso)
            # end_of_turn == True → es el final del turno (emisión completa)
            if event.end_of_turn:
                # Turno final - fijar la línea y limpiar para la siguiente
                text = event.transcript or ""
                if text.strip():
                    on_final_callback(text.strip(), list(self.accumulated_words))
                    self.accumulated_words.clear()  # Limpiar para el siguiente turno
            else:
                # Turno parcial - reemplazar la línea en curso
                if on_partial_callback:
                    partial_text = event.transcript or ""
                    if partial_text:
                        on_partial_callback(partial_text)

        def handle_error(client: StreamingClient, error):
            print(f"[AssemblyAI Error] {error}")

        # Crear el cliente con la API key
        options = StreamingClientOptions(api_key=self.api_key)
        self.client = StreamingClient(options=options)

        # Registrar handlers usando .on()
        self.client.on(StreamingEvents.Turn, handle_turn)
        self.client.on(StreamingEvents.Error, handle_error)

        # Conectar con los parámetros de streaming
        params = StreamingParameters(
            speech_model="universal-3-5-pro",
            sample_rate=sample_rate,
            format_turns=True,  # Texto con puntuación y mayúsculas
            include_partial_turns=True,  # Recibir parciales (end_of_turn=False)
        )

        self.client.connect(params)
        self.is_connected = True
        print("[AssemblyAI] Streaming STT Universal-3.5 Pro conectado.")

    def stream_audio_chunk(self, chunk: bytes):
        """Envía un fragmento de audio PCM (16-bit, 16kHz mono) al WebSocket."""
        if self.client and self.is_connected:
            self.client.stream(chunk)

    def stop(self):
        """Cierra la conexión WebSocket limpiamente y libera la sesión STT."""
        if self.client and self.is_connected:
            try:
                self.client.disconnect(terminate=True)
            except Exception as e:
                print(f"[AssemblyAI] Error al desconectar: {e}")
            finally:
                self.client = None
                self.is_connected = False
                print("[AssemblyAI] Transcriptor desconectado.")

    def detect_silences_and_dead_air(self, min_silence_ms: int = 350) -> List[Dict[str, int]]:
        """
        Analiza los timestamps acumulados y detecta baches de silencio para corte automático.
        """
        cuts = []
        if len(self.accumulated_words) < 2:
            return cuts

        for i in range(len(self.accumulated_words) - 1):
            curr_end = self.accumulated_words[i].end_ms
            next_start = self.accumulated_words[i + 1].start_ms
            gap = next_start - curr_end
            if gap >= min_silence_ms:
                cuts.append({
                    "silence_start_ms": curr_end,
                    "silence_end_ms": next_start,
                    "duration_ms": gap,
                    "after_word": self.accumulated_words[i].word,
                    "before_word": self.accumulated_words[i + 1].word,
                })
        return cuts

    def export_hormozi_captions_json(self) -> List[Dict[str, Any]]:
        """
        Exporta los datos de palabras formateados para el motor de subtítulos de Remotion.
        """
        return [
            {
                "text": w.word.upper(),
                "start": round(w.start_ms / 1000.0, 3),
                "end": round(w.end_ms / 1000.0, 3),
                "duration": round((w.end_ms - w.start_ms) / 1000.0, 3),
            }
            for w in self.accumulated_words
        ]


# ========================================================================================
# RUTA A: CLIENTE WEBSOCKET VOICE AGENT API CON TOOL CALLING
# ========================================================================================

class AssemblyAIVoiceAgentClient:
    """
    Cliente WebSocket para la Voice Agent API gestionada de AssemblyAI.
    Soporta VAD nativo, interrupción (barge-in) y despacho de herramientas.
    """

    def __init__(self, api_key: Optional[str] = None):
        from app.config import settings
        self.api_key = api_key or settings.assemblyai_api_key
        self.ws_url = "wss://agents.assemblyai.com/v1/ws"
        self.tool_handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

    def register_tool(self, name: str, handler: Callable[[Dict[str, Any]], Any]):
        """Registra una función local que el agente puede invocar por voz."""
        self.tool_handlers[name] = handler

    async def run_voice_session(
        self,
        system_prompt: str,
        tools_schema: List[Dict[str, Any]],
        voice: str = "brian",
    ):
        """
        Ejecuta la sesión del Voice Agent bidireccional sobre WebSocket.
        Requiere 'websockets' (`pip install websockets`).
        """
        try:
            import websockets
        except ImportError:
            raise RuntimeError("Instale websockets: pip install websockets")

        headers = {"Authorization": f"Bearer {self.api_key}"}

        print(f"[Voice Agent] Conectando a {self.ws_url}...")
        async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
            # 1. Configurar la sesión
            init_payload = {
                "type": "session.update",
                "system_prompt": system_prompt,
                "voice": voice,
                "tools": tools_schema,
            }
            await ws.send(json.dumps(init_payload))
            print("[Voice Agent] Sesion inicializada con herramientas registradas.")

            # 2. Loop de escucha de eventos
            async for message in ws:
                event = json.loads(message)
                event_type = event.get("type")

                if event_type == "session.ready":
                    print(f"[Voice Agent] Listo. Session ID: {event.get('session_id')}")

                elif event_type == "transcript":
                    text = event.get("text", "")
                    if text:
                        print(f"[Usuario]: {text}")

                elif event_type == "tool.call":
                    tool_id = event.get("tool_call_id")
                    name = event.get("name")
                    arguments = event.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            pass

                    print(f"[Tool Call]: {name}({arguments})")

                    # Ejecutar handler registrado
                    result_data = {"status": "error", "message": f"Herramienta {name} no registrada."}
                    if name in self.tool_handlers:
                        try:
                            result_data = self.tool_handlers[name](arguments)
                        except Exception as e:
                            result_data = {"status": "error", "error": str(e)}

                    # Responder al agente con el resultado
                    response_payload = {
                        "type": "tool.result",
                        "tool_call_id": tool_id,
                        "result": json.dumps(result_data),
                    }
                    await ws.send(json.dumps(response_payload))
                    print(f"[Tool Result Enviado]: {name}")

                elif event_type == "reply.done":
                    print("[Agente]: Turno completado.")
