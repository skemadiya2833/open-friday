/* Friday conversational turn-taking (browser).
 *
 * Ideas only (no copied code) from:
 *   - OpenAI Realtime semantic_vad / server_vad eagerness timeouts
 *     https://developers.openai.com/api/docs/guides/realtime-vad
 *   - Deepgram utterance_end_ms (≥1000ms word-gap) + VAD endpointing
 *     https://developers.deepgram.com/docs/understanding-end-of-speech-detection
 *   - Azure Speech segmentationSilenceTimeoutMs (longer = tolerate mid-phrase pauses)
 *     https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech
 *   - Chrome Web Speech API: continuous + interimResults; finals ≠ end of thought
 *     https://developer.chrome.com/blog/voice-driven-web-apps-introduction-to-the-web-speech-api
 *
 * Algorithm: commit a turn only when (1) mic energy has been quiet, (2) no interim
 * hypothesis is open, and (3) either the transcript looks semantically complete with
 * a short silence, or a max eagerness timeout elapses. Chrome `isFinal` alone never
 * commits — that was cutting people off mid-breath.
 */
(function () {
  "use strict";

  // Eagerness bands inspired by OpenAI semantic_vad (low≈8s / medium≈4s / high≈2s max).
  const EAGER = {
    high: {
      completeSilenceMs: 380,
      incompleteSilenceMs: 900,
      maxWaitMs: 1400,
      energyQuietMs: 200,
      energyThresh: 0.045,
    },
    medium: {
      completeSilenceMs: 900,
      incompleteSilenceMs: 2200,
      maxWaitMs: 5200,
      energyQuietMs: 360,
      energyThresh: 0.04,
    },
    low: {
      completeSilenceMs: 1200,
      incompleteSilenceMs: 2800,
      maxWaitMs: 7500,
      energyQuietMs: 420,
      energyThresh: 0.035,
    },
  };

  const SHORT_DONE = /^(yes|yeah|yep|no|nope|ok|okay|sure|thanks|thank you|stop|cancel|wait|hello|hi|hey)\b/i;
  const TRAIL_OPEN =
    /\b(and|or|but|so|because|if|when|while|then|that|which|who|whose|whom|a|an|the|to|of|for|with|my|your|our|their|i|i'm|i'll|i've|i'd|it's|there's|we're|they're|um+|uh+|erm+|like|basically|actually|so yeah)\s*$/i;
  const ENDS_PUNCT = /[.!?…]["']?\s*$/;
  const IMPERATIVE =
    /^(please\s+)?(open|close|show|display|put|bring|pull|list|run|launch|start|stop|cancel|mute|unmute|set|remind|schedule|search|find|look|go|click|type|write|send|play|pause|next|previous)\b/i;

  function wordCount(t) {
    return (t || "").trim().split(/\s+/).filter(Boolean).length;
  }

  /** @returns {{score: number, reason: string}} score 0..1 — higher = more likely done speaking */
  function completeness(text) {
    const t = (text || "").trim();
    if (!t) return { score: 0, reason: "empty" };
    const wc = wordCount(t);
    if (SHORT_DONE.test(t) && wc <= 4) return { score: 0.95, reason: "short_ack" };
    if (ENDS_PUNCT.test(t)) return { score: 0.92, reason: "punct" };
    if (TRAIL_OPEN.test(t)) return { score: 0.15, reason: "trailing_open" };
    if (/,[\s]*$/.test(t)) return { score: 0.25, reason: "comma_trail" };
    if (IMPERATIVE.test(t) && wc >= 2 && wc <= 14 && !TRAIL_OPEN.test(t)) {
      return { score: 0.82, reason: "imperative" };
    }
    if (wc <= 2) return { score: 0.35, reason: "very_short" };
    if (wc <= 5) return { score: 0.55, reason: "short" };
    // Longer clause without open trail — moderately complete
    return { score: 0.7, reason: "clause" };
  }

  function micLevel() {
    try {
      if (window.FridayLive && typeof FridayLive.micLevel === "function") {
        return FridayLive.micLevel();
      }
    } catch (_) {}
    return 0;
  }

  function TurnDetector(opts) {
    this.getEagerness = opts.getEagerness || (() => "medium");
    this.onCommit = opts.onCommit || (() => {});
    this.onHold = opts.onHold || (() => {});
    this._timer = null;
    this._lastResultAt = 0;
    this._lastHotAt = 0;
    this._speaking = false;
    this._armed = false;
    this._energyIv = null;
  }

  TurnDetector.prototype.cfg = function () {
    return EAGER[this.getEagerness()] || EAGER.medium;
  };

  TurnDetector.prototype.startEnergyWatch = function () {
    if (this._energyIv) return;
    this._energyIv = setInterval(() => {
      if (!this._armed) return;
      const c = this.cfg();
      const lvl = micLevel();
      if (lvl >= c.energyThresh) {
        this._lastHotAt = Date.now();
        this._speaking = true;
        // User is still vocalizing — never let a pending commit fire.
        if (this._timer) this._rearm();
      } else if (this._speaking && Date.now() - this._lastHotAt > c.energyQuietMs) {
        this._speaking = false;
        this._rearm();
      }
    }, 50);
  };

  TurnDetector.prototype.stopEnergyWatch = function () {
    if (this._energyIv) {
      clearInterval(this._energyIv);
      this._energyIv = null;
    }
  };

  TurnDetector.prototype.reset = function () {
    this.cancel();
    this._lastResultAt = 0;
    this._lastHotAt = 0;
    this._speaking = false;
    this._armed = false;
  };

  TurnDetector.prototype.cancel = function () {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  };

  TurnDetector.prototype.noteSpeechStart = function () {
    this._speaking = true;
    this._lastHotAt = Date.now();
    this.cancel();
  };

  TurnDetector.prototype.noteSpeechEnd = function () {
    // Browser thinks speech ended — still wait for semantic + energy quiet.
    this._rearm();
  };

  /**
   * @param {{finalText: string, interimText: string}} state
   */
  TurnDetector.prototype.noteResult = function (state) {
    this._armed = true;
    this._lastResultAt = Date.now();
    if (micLevel() >= this.cfg().energyThresh) this._lastHotAt = Date.now();
    this.startEnergyWatch();
    this._state = state;
    this._rearm();
  };

  TurnDetector.prototype._rearm = function () {
    this.cancel();
    if (!this._armed || !this._state) return;
    const c = this.cfg();
    const text = `${this._state.finalText || ""} ${this._state.interimText || ""}`.trim();
    if (!text) return;

    const hasInterim = !!(this._state.interimText || "").trim();
    const { score, reason } = completeness(text);
    const needSilence = Math.round(
      c.incompleteSilenceMs + (c.completeSilenceMs - c.incompleteSilenceMs) * score,
    );
    // Cap by eagerness max — always eventually commit so we don't hang forever.
    const sinceResult = Date.now() - this._lastResultAt;
    const sinceHot = Date.now() - (this._lastHotAt || this._lastResultAt);
    const quietEnough = sinceHot >= c.energyQuietMs && !this._speaking;
    const waitedMax = sinceResult >= c.maxWaitMs;

    // Chrome often leaves an interim hypothesis open forever — still commit on max wait
    // so we never freeze on LISTENING with a full transcript and no send.
    if (hasInterim && !waitedMax) {
      this.onHold({ reason: "interim", score, needSilence, text });
      this._timer = setTimeout(() => this._rearm(), 120);
      return;
    }
    // No usable mic energy meter → don't wait forever for "quiet".
    const energyUnknown = micLevel() <= 0 && sinceResult > 600;
    if (!quietEnough && !waitedMax && !energyUnknown) {
      this.onHold({ reason: "mic_hot", score, needSilence, text });
      this._timer = setTimeout(() => this._rearm(), 80);
      return;
    }
    if (sinceResult < needSilence && !waitedMax) {
      this.onHold({ reason: reason || "waiting", score, needSilence, text, remain: needSilence - sinceResult });
      this._timer = setTimeout(() => this._rearm(), Math.min(120, Math.max(40, needSilence - sinceResult)));
      return;
    }

    // Commit
    this._armed = false;
    this.cancel();
    this.onCommit({
      text,
      score,
      reason: waitedMax ? "max_wait" : reason,
      silenceMs: sinceResult,
    });
  };

  // Expose helpers for unit-ish checks in console / tests
  window.FridayTurn = {
    EAGER,
    completeness,
    TurnDetector,
  };
})();
