# Recording your voice for the speech-recognition benchmark (about 5 minutes)

Why: Whisper accuracy depends on YOUR voice, accent and microphone. Synthetic clips only prove the plumbing.
Until you do this, `large-v3-turbo` float16 is a PROVISIONAL default and its accuracy for you is UNVERIFIED.

Nothing leaves your PC. Clips are saved as 16 kHz mono WAV in `data/voice_lab/real/` (git-ignored).

## Steps (PowerShell, in the project folder)

1. Close the benchmark or any other GPU-heavy job. Sit where you normally sit, use your normal microphone.
2. Record the 12 commands (press Enter, speak the sentence, it stops after you go quiet):

   ```powershell
   friday_env\Scripts\python.exe scripts\record_stt_samples.py
   ```

   - `--list` shows the sentences. `--redo 5` re-records sentence 5.
   - Speak at normal pace. Say numbers as words, exactly as printed. Read each sentence as written.
   - Want more coverage? Add your own sentences to `PROMPTS` in the script (10-15 is a good size). Include your real names for apps, folders and people, since those are the hard words.
3. Run the benchmark (loads each model once, a few minutes the first time because models download):

   ```powershell
   friday_env\Scripts\python.exe scripts\bench_stt_real.py --models large-v3-turbo small base
   ```

   Output: word error rate (WER) per model and per clip, and seconds per clip. It writes a JSON file under `docs/research/`.
4. Decide: pick the smallest model whose WER you are happy with (rule of thumb: under about 10% on commands). Then set it in `.env`:

   ```
   VOICE_STT_MODEL=large-v3-turbo
   ```

   If `.env` already has `VOICE_STT_MODEL=base`, that value wins over the code default (the code default changed to `large-v3-turbo`).

## Known-good runtime versions on this PC (RTX 5060 Ti, driver 617.14)
- faster-whisper with CTranslate2 4.8.2 (pinned in `requirements/voice.lock.txt`), CUDA 12.8 cuBLAS visible on PATH, cuDNN 9.10.2.21 (bundled with the pinned wheels). Measured numbers: `docs/research/stt_bench.json`.
- If CUDA fails to load, STT automatically falls back to CPU (`int8`) and says so in the log. Force with `VOICE_STT_DEVICE=cpu`.

## Privacy
The recordings are your voice. Do not commit or share them. `data/` is git-ignored.
