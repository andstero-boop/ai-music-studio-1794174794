package com.example.aimusicstudio

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import kotlin.concurrent.thread
import kotlin.math.*

class AutoTuneProcessor {
    @Volatile var isRunning = false
    @Volatile var retuneSpeed = 0.85f
    @Volatile var rootKey = 0
    @Volatile var scaleType = "Minor"
    var onPitchDetected: ((String, Int, Int) -> Unit)? = null

    private val noteNames = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    private var workerThread: Thread? = null

    private val scales = mapOf(
        "Major" to intArrayOf(0, 2, 4, 5, 7, 9, 11),
        "Minor" to intArrayOf(0, 2, 3, 5, 7, 8, 10),
        "Pentatonic" to intArrayOf(0, 3, 5, 7, 10),
        "Chromatic" to intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
    )

    @SuppressLint("MissingPermission")
    fun start() {
        if (isRunning) return
        isRunning = true
        workerThread = thread(start = true, name = "AutoTuneDSP") {
            val sr = 44100
            val frameSize = 1024
            val minRecBuf = AudioRecord.getMinBufferSize(
                sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            val recorder = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION, sr,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                max(minRecBuf, frameSize * 4)
            )
            val minPlayBuf = AudioTrack.getMinBufferSize(
                sr, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            val player = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(sr)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(max(minPlayBuf, frameSize * 4))
                .build()

            val inBuf = ShortArray(frameSize)
            val outBuf = ShortArray(frameSize)
            var smoothedRatio = 1.0
            var readPhase = 0.0
            val ringSize = frameSize * 4
            val ringBuffer = ShortArray(ringSize)
            var writePos = 0

            recorder.startRecording()
            player.play()

            while (isRunning) {
                val read = recorder.read(inBuf, 0, frameSize)
                if (read <= 0) continue
                for (i in 0 until read) {
                    ringBuffer[(writePos + i) % ringSize] = inBuf[i]
                }
                val detectedFreq = detectPitchAutocorrelation(inBuf, read, sr)
                var targetRatio = 1.0
                if (detectedFreq in 75.0..900.0) {
                    val detectedMidi = 69.0 + 12.0 * log2(detectedFreq / 440.0)
                    val targetMidi = snapToScale(detectedMidi.roundToInt())
                    val targetFreq = 440.0 * 2.0.pow((targetMidi - 69) / 12.0)
                    targetRatio = (targetFreq / detectedFreq).coerceIn(0.5, 2.0)
                    val noteStr = noteNames[targetMidi % 12] + (targetMidi / 12 - 1)
                    onPitchDetected?.invoke(noteStr, detectedFreq.roundToInt(), targetFreq.roundToInt())
                } else {
                    onPitchDetected?.invoke("--", 0, 0)
                }
                smoothedRatio += (targetRatio - smoothedRatio) * retuneSpeed
                for (i in 0 until read) {
                    val idx0 = readPhase.toInt() % ringSize
                    val idx1 = (idx0 + 1) % ringSize
                    val frac = readPhase - floor(readPhase)
                    val s0 = ringBuffer[if (idx0 < 0) idx0 + ringSize else idx0]
                    val s1 = ringBuffer[if (idx1 < 0) idx1 + ringSize else idx1]
                    outBuf[i] = (s0 + frac * (s1 - s0)).toInt().coerceIn(-32768, 32767).toShort()
                    readPhase = (readPhase + smoothedRatio) % ringSize
                }
                writePos = (writePos + read) % ringSize
                player.write(outBuf, 0, read)
            }
            recorder.stop()
            recorder.release()
            player.stop()
            player.release()
        }
    }

    fun stop() {
        isRunning = false
        workerThread?.join(400)
        workerThread = null
    }

    private fun snapToScale(midiNote: Int): Int {
        val allowedIntervals = scales[scaleType] ?: scales["Minor"]!!
        val octave = midiNote / 12
        val relPitch = (midiNote % 12 - rootKey + 12) % 12
        var bestInterval = allowedIntervals[0]
        var minDiff = 99
        for (interval in allowedIntervals) {
            val diff = abs(relPitch - interval)
            if (diff < minDiff) {
                minDiff = diff
                bestInterval = interval
            }
        }
        return octave * 12 + ((rootKey + bestInterval) % 12)
    }

    private fun detectPitchAutocorrelation(buffer: ShortArray, length: Int, sampleRate: Int): Double {
        var rms = 0.0
        for (i in 0 until length) {
            val v = buffer[i] / 32768.0
            rms += v * v
        }
        rms = sqrt(rms / length)
        if (rms < 0.015) return -1.0
        val minLag = sampleRate / 900
        val maxLag = min(length / 2, sampleRate / 75)
        var bestLag = -1
        var maxCorr = 0.0
        for (lag in minLag..maxLag) {
            var corr = 0.0
            for (i in 0 until length - lag) {
                corr += (buffer[i] / 32768.0) * (buffer[i + lag] / 32768.0)
            }
            if (corr > maxCorr) {
                maxCorr = corr
                bestLag = lag
            }
        }
        return if (bestLag > 0) sampleRate.toDouble() / bestLag else -1.0
    }
}
