# Voice: speaker+mic echo and natural TTS (2026-10-11)

## Setup we care about
Monitor speakers + desk mic in front of the screen. Browser WebRTC AEC often fails here (same class as mobile loudspeaker / kiosk).

## What others do
| Source | Approach |
|--------|----------|
| [Deepgram — Audio preprocessing & barge-in](https://developers.deepgram.com/guides/deep-dives/audio-preprocessing-barge-in) | Enable OS/browser AEC first; true barge-in needs speech-aware detection, not energy VAD alone |
| [Coval — Voice AI echo cancellation](https://www.coval.ai/blog/voice-ai-echo-cancellation/) | Half-duplex / ducking when AEC fails; headphones when software cannot win |
| [protoVoice audio handling](https://protolabsai.github.io/protoVoice/guides/audio-handling.html) | Echo-guard tail ~300ms after TTS; half-duplex for loud playback / Bluetooth |
| [my-ax half-duplex gate](https://github.com/acoyfellow/my-ax/commit/e4d4dcf52250f23cc542cab02e5cd459b3037f98) | Mute STT while thinking/speaking; re-arm ~400ms after idle |
| [Telenow client](https://www.npmjs.com/package/@telenow/client) | `turnTaking: 'halfDuplex'` for emulators / loudspeakers |

**Chosen for Friday:** Hold (half-duplex) default + ~750ms echo-tail re-arm. Interrupt remains optional (echo risk).

## Natural voice
Browser SpeechSynthesis + playbackRate > 1× sounded robotic. Edge neural at `+0%` rate is the default path for Realtime and Relaxed. Default voice: `en-US-AvaNeural` (alts Jenny / Aria / Sonia). Pace via “speak slower/faster/normally”, not a slider.
