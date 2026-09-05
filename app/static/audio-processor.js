/**
 * AudioWorklet processor for converting Float32 to PCM16 at 24kHz
 * Intended for AssemblyAI Voice Agent WebSocket transmission
 */

class AssemblyAIAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Configuration: 24kHz sample rate as required by AssemblyAI Voice Agent
    this.targetSampleRate = 24000;
    // Buffer for downsampling if input is at different rate
    this.buffer = [];
  }

  /**
   * Main processing function called by Web Audio API
   * @param {Float32Array[][]} inputs - Input channels
   * @param {Float32Array[][]} outputs - Output channels (not used here, we postMessage)
   * @param {object} parameters - Audio parameters
   * @returns {boolean} True to keep processor alive
   */
  process(inputs, outputs, parameters) {
    const input = inputs[0];

    if (input.length > 0 && input[0].length > 0) {
      // Get the first channel (mono audio assumed)
      const inputData = input[0];

      // Convert Float32 audio to PCM16 (Int16)
      // AssemblyAI expects PCM16 audio data
      const pcmData = this.floatToPCM16(inputData);

      // Send the PCM16 data to the main thread for WebSocket transmission
      this.port.postMessage({
        type: 'audio',
        data: pcmData
      });
    }

    return true; // Keep the processor alive
  }

  /**
   * Convert Float32 samples to PCM16 (Int16)
   * @param {Float32Array} float32Samples - Input audio samples
   * @returns {Int16Array} PCM16 audio samples
   */
  floatToPCM16(float32Samples) {
    const int16Samples = new Int16Array(float32Samples.length);

    for (let i = 0; i < float32Samples.length; i++) {
      // Clamp value between -1 and 1
      let sample = Math.max(-1, Math.min(1, float32Samples[i]));

      // Convert to 16-bit integer range [-32768, 32767]
      int16Samples[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
    }

    return int16Samples;
  }
}

// Register the processor with the AudioWorklet global scope
registerProcessor('assembly-audio-processor', AssemblyAIAudioProcessor);
