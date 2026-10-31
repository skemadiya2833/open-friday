"""Mel / WAV helpers for Wav2Lip — numpy only (no librosa/scipy).

PyPI pulls for scipy/librosa are huge and often flake on flaky links;
inference only needs load_wav + melspectrogram matching the training hparams.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from hparams import hparams as hp

_mel_basis = None


def load_wav(path, sr):
    path = str(path)
    with wave.open(path, "rb") as wf:
        n_ch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    if sw == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    elif sw == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    elif sw == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 65536.0
    else:
        raise ValueError(f"Unsupported sample width {sw} in {path}")
    if n_ch > 1:
        audio = audio.reshape(-1, n_ch).mean(axis=1)
    audio = audio / 32768.0
    if rate != sr:
        audio = _resample_linear(audio, rate, sr)
    return audio


def save_wav(wav, path, sr):
    wav = np.asarray(wav, dtype=np.float64)
    wav = wav * (32767.0 / max(0.01, np.max(np.abs(wav))))
    pcm = np.clip(wav, -32768, 32767).astype(np.int16)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())


def save_wavenet_wav(wav, path, sr):
    save_wav(wav, path, sr)


def preemphasis(wav, k, preemphasize=True):
    if not preemphasize:
        return wav
    wav = np.asarray(wav, dtype=np.float64)
    out = np.empty_like(wav)
    out[0] = wav[0]
    out[1:] = wav[1:] - k * wav[:-1]
    return out.astype(np.float32, copy=False)


def inv_preemphasis(wav, k, inv_preemphasize=True):
    if not inv_preemphasize:
        return wav
    wav = np.asarray(wav, dtype=np.float64)
    out = np.empty_like(wav)
    out[0] = wav[0]
    for i in range(1, len(wav)):
        out[i] = wav[i] + k * out[i - 1]
    return out.astype(np.float32, copy=False)


def get_hop_size():
    hop_size = hp.hop_size
    if hop_size is None:
        assert hp.frame_shift_ms is not None
        hop_size = int(hp.frame_shift_ms / 1000 * hp.sample_rate)
    return hop_size


def linearspectrogram(wav):
    D = _stft(preemphasis(wav, hp.preemphasis, hp.preemphasize))
    S = _amp_to_db(np.abs(D)) - hp.ref_level_db
    if hp.signal_normalization:
        return _normalize(S)
    return S


def melspectrogram(wav):
    D = _stft(preemphasis(wav, hp.preemphasis, hp.preemphasize))
    S = _amp_to_db(_linear_to_mel(np.abs(D))) - hp.ref_level_db
    if hp.signal_normalization:
        return _normalize(S)
    return S


def _stft(y):
    if hp.use_lws:
        raise RuntimeError("lws STFT not supported in numpy audio shim")
    n_fft = int(hp.n_fft)
    hop = int(get_hop_size())
    win = int(hp.win_size)
    window = np.hanning(win).astype(np.float64)
    # librosa.stft default center=True → pad n_fft//2 on each side
    y = np.asarray(y, dtype=np.float64)
    pad = n_fft // 2
    y_pad = np.pad(y, pad, mode="reflect")
    n_frames = 1 + (len(y_pad) - n_fft) // hop
    # pad window into n_fft if needed
    if win < n_fft:
        w = np.zeros(n_fft, dtype=np.float64)
        off = (n_fft - win) // 2
        w[off : off + win] = window
        window = w
    elif win > n_fft:
        window = window[:n_fft]
    out = np.empty((n_fft // 2 + 1, n_frames), dtype=np.complex128)
    for i in range(n_frames):
        start = i * hop
        frame = y_pad[start : start + n_fft] * window
        out[:, i] = np.fft.rfft(frame)
    return out


def num_frames(length, fsize, fshift):
    pad = fsize - fshift
    if length % fshift == 0:
        return (length + pad * 2 - fsize) // fshift + 1
    return (length + pad * 2 - fsize) // fshift + 2


def pad_lr(x, fsize, fshift):
    M = num_frames(len(x), fsize, fshift)
    pad = fsize - fshift
    T = len(x) + 2 * pad
    r = (M - 1) * fshift + fsize - T
    return pad, pad + r


def librosa_pad_lr(x, fsize, fshift):
    return 0, (x.shape[0] // fshift + 1) * fshift - x.shape[0]


def _linear_to_mel(spectogram):
    global _mel_basis
    if _mel_basis is None:
        _mel_basis = _build_mel_basis()
    return np.dot(_mel_basis, spectogram)


def _hz_to_mel_slaney(frequencies):
    frequencies = np.asanyarray(frequencies, dtype=np.float64)
    f_sp = 200.0 / 3
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    mels = frequencies / f_sp
    log_t = frequencies >= min_log_hz
    mels[log_t] = min_log_mel + np.log(frequencies[log_t] / min_log_hz) / logstep
    return mels


def _mel_to_hz_slaney(mels):
    mels = np.asanyarray(mels, dtype=np.float64)
    f_sp = 200.0 / 3
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    freqs = mels * f_sp
    log_t = mels >= min_log_mel
    freqs[log_t] = min_log_hz * np.exp(logstep * (mels[log_t] - min_log_mel))
    return freqs


def _build_mel_basis():
    assert hp.fmax <= hp.sample_rate // 2
    n_fft = int(hp.n_fft)
    n_mels = int(hp.num_mels)
    sr = int(hp.sample_rate)
    fmin = float(hp.fmin)
    fmax = float(hp.fmax)
    # Match librosa.filters.mel(..., htk=False, norm='slaney')
    n_freqs = n_fft // 2 + 1
    weights = np.zeros((n_mels, n_freqs), dtype=np.float64)
    fftfreqs = np.linspace(0, sr / 2, n_freqs)
    m_min = _hz_to_mel_slaney(np.array([fmin]))[0]
    m_max = _hz_to_mel_slaney(np.array([fmax]))[0]
    m_pts = np.linspace(m_min, m_max, n_mels + 2)
    freqs = _mel_to_hz_slaney(m_pts)
    fdiff = np.diff(freqs)
    ramps = np.subtract.outer(freqs, fftfreqs)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (freqs[2 : n_mels + 2] - freqs[:n_mels])
    weights *= enorm[:, np.newaxis]
    return weights


def _amp_to_db(x):
    min_level = np.exp(hp.min_level_db / 20 * np.log(10))
    return 20 * np.log10(np.maximum(min_level, x))


def _db_to_amp(x):
    return np.power(10.0, x * 0.05)


def _normalize(S):
    if hp.allow_clipping_in_normalization:
        if hp.symmetric_mels:
            return np.clip(
                (2 * hp.max_abs_value) * ((S - hp.min_level_db) / (-hp.min_level_db))
                - hp.max_abs_value,
                -hp.max_abs_value,
                hp.max_abs_value,
            )
        return np.clip(
            hp.max_abs_value * ((S - hp.min_level_db) / (-hp.min_level_db)),
            0,
            hp.max_abs_value,
        )
    assert S.max() <= 0 and S.min() - hp.min_level_db >= 0
    if hp.symmetric_mels:
        return (2 * hp.max_abs_value) * ((S - hp.min_level_db) / (-hp.min_level_db)) - hp.max_abs_value
    return hp.max_abs_value * ((S - hp.min_level_db) / (-hp.min_level_db))


def _denormalize(D):
    if hp.allow_clipping_in_normalization:
        if hp.symmetric_mels:
            return (
                (
                    (np.clip(D, -hp.max_abs_value, hp.max_abs_value) + hp.max_abs_value)
                    * -hp.min_level_db
                    / (2 * hp.max_abs_value)
                )
                + hp.min_level_db
            )
        return (np.clip(D, 0, hp.max_abs_value) * -hp.min_level_db / hp.max_abs_value) + hp.min_level_db
    if hp.symmetric_mels:
        return ((D + hp.max_abs_value) * -hp.min_level_db / (2 * hp.max_abs_value)) + hp.min_level_db
    return (D * -hp.min_level_db / hp.max_abs_value) + hp.min_level_db


def _resample_linear(x, orig_sr, target_sr):
    if orig_sr == target_sr:
        return x
    duration = len(x) / float(orig_sr)
    n_out = int(round(duration * target_sr))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    t_old = np.linspace(0, duration, num=len(x), endpoint=False)
    t_new = np.linspace(0, duration, num=n_out, endpoint=False)
    return np.interp(t_new, t_old, x).astype(np.float32)
