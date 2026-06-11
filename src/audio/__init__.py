"""Real audio pipeline for the Vivi voice retention and FDRC tracks.

Turns Vietnamese text into spoken audio (ElevenLabs), mixes in cabin/road noise,
and exposes a disk-cached interface used by the orchestrator to stream audio into
the OpenAI Realtime session. All audio is normalized to PCM16 mono 24 kHz.
"""
