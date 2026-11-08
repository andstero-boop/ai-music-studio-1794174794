package com.example.aimusicstudio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.Environment
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.concurrent.thread
import kotlin.math.*
import kotlin.random.Random

class SynthEngine {
    companion object {
        const val SAMPLE_RATE = 44100
        const val NUM_TRACKS = 8
        const val NUM_STEPS = 16
        val TRACK_NAMES = arrayOf(
            "Kick", "Snare", "Hi-Hat", "Clap",
            "Sub Bass", "Saw Lead", "FM Keys", "Warm Pad"
        )
    }

    val grid = Array(NUM_TRACKS) { IntArray(NUM_STEPS) { 0 } }
    val trackMuted = BooleanArray(NUM_TRACKS) { false }

    @Volatile var isPlaying = false
    @Volatile var bpm = 120
    @Volatile var currentStep = 0
    var onStepChanged: ((Int) -> Unit)? = null

    private var audioThread: Thread? = null

    fun start() {
        if (isPlaying) return
        isPlaying = true
        audioThread = thread(start = true, name = "DAWAudioThread") { runAudioLoop() }
    }

    fun stop() {
        isPlaying = false
        audioThread?.join(500)
        audioThread = null
    }

    fun midiToFreq(midi: Int): Double = 440.0 * 2.0.pow((midi - 69) / 12.0)

    fun getTrackBaseMidi(track: Int): Int = when (track) {
        4 -> 36
        5 -> 60
        6 -> 53
        7 -> 48
        else -> 36
    }

    fun triggerNotePreview(track: Int, midiNote: Int) {
        thread(start = true, name = "NotePreview") {
            val numSamples = (SAMPLE_RATE * 0.22).toInt()
            val previewBuf = ShortArray(numSamples)
            val active = IntArray(NUM_TRACKS) { 0 }
            active[track] = midiNote
            renderNotesToBuffer(active, previewBuf, numSamples)

            val minBuf = AudioTrack.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            val trackOut = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(max(minBuf, previewBuf.size * 2))
                .setTransferMode(AudioTrack.MODE_STATIC)
                .build()

            trackOut.write(previewBuf, 0, previewBuf.size)
            trackOut.play()
            Thread.sleep(240)
            trackOut.stop()
            trackOut.release()
        }
    }

    private fun runAudioLoop() {
        val minBuf = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(max(minBuf, 4096))
            .build()

        audioTrack.play()
        var stepIdx = 0

        while (isPlaying) {
            currentStep = stepIdx
            onStepChanged?.invoke(stepIdx)
            val samplesPerStep = (SAMPLE_RATE * 60.0 / bpm / 4.0).toInt()
            val stepBuffer = renderStepSamples(stepIdx, samplesPerStep)
            audioTrack.write(stepBuffer, 0, stepBuffer.size)
            stepIdx = (stepIdx + 1) % NUM_STEPS
        }

        audioTrack.stop()
        audioTrack.release()
    }

    fun renderStepSamples(stepIdx: Int, numSamples: Int): ShortArray {
        val out = ShortArray(numSamples)
        val activeNotes = IntArray(NUM_TRACKS) { t ->
            if (trackMuted[t]) 0 else grid[t][stepIdx]
        }
        renderNotesToBuffer(activeNotes, out, numSamples)
        return out
    }

    private fun renderNotesToBuffer(activeNotes: IntArray, out: ShortArray, numSamples: Int) {
        for (i in 0 until numSamples) {
            val t = i.toDouble() / SAMPLE_RATE
            val progress = i.toDouble() / numSamples
            var mix = 0.0

            if (activeNotes[0] > 0) {
                val env = exp(-t * 18.0)
                val freq = 140.0 * exp(-t * 32.0) + 42.0
                mix += sin(2.0 * PI * freq * t) * env * 0.9
            }
            if (activeNotes[1] > 0) {
                val noiseEnv = exp(-t * 26.0)
                val bodyEnv = exp(-t * 40.0)
                val noise = (Random.nextDouble() * 2.0 - 1.0) * noiseEnv * 0.55
                val body = sin(2.0 * PI * 185.0 * t) * bodyEnv * 0.45
                mix += (noise + body)
            }
            if (activeNotes[2] > 0) {
                val env = exp(-t * 65.0)
                val metallic = sin(2.0 * PI * 6400.0 * t) * sin(2.0 * PI * 9100.0 * t)
                val noise = (Random.nextDouble() * 2.0 - 1.0)
                mix += (noise * 0.7 + metallic * 0.3) * env * 0.45
            }
            if (activeNotes[3] > 0) {
                val retrigger = if (t < 0.012 || (t > 0.018 && t < 0.028)) 1.0 else exp(-t * 24.0)
                val noise = (Random.nextDouble() * 2.0 - 1.0) * retrigger
                mix += noise * 0.5
            }
            if (activeNotes[4] > 0) {
                val freq = midiToFreq(activeNotes[4])
                val env = (1.0 - progress).pow(0.6)
                val fundamental = sin(2.0 * PI * freq * t)
                val subHarmonic = if (sin(2.0 * PI * (freq * 0.5) * t) >= 0) 0.25 else -0.25
                mix += tanh((fundamental + subHarmonic) * 1.6) * env * 0.55
            }
            if (activeNotes[5] > 0) {
                val freq = midiToFreq(activeNotes[5])
                val env = exp(-t * 6.5)
                val saw1 = 2.0 * (t * freq - floor(0.5 + t * freq))
                val saw2 = 2.0 * (t * (freq * 1.006) - floor(0.5 + t * (freq * 1.006)))
                mix += (saw1 + saw2) * 0.5 * env * 0.38
            }
            if (activeNotes[6] > 0) {
                val freq = midiToFreq(activeNotes[6])
                val modEnv = exp(-t * 14.0)
                val ampEnv = exp(-t * 5.0)
                val modulator = sin(2.0 * PI * (freq * 2.0) * t) * 2.5 * modEnv
                val carrier = sin(2.0 * PI * freq * t + modulator)
                mix += carrier * ampEnv * 0.42
            }
            if (activeNotes[7] > 0) {
                val root = midiToFreq(activeNotes[7])
                val fifth = midiToFreq(activeNotes[7] + 7)
                val attackRelease = sin(PI * progress)
                val chord = (sin(2.0 * PI * root * t) +
                             sin(2.0 * PI * fifth * t) * 0.7 +
                             sin(2.0 * PI * (root * 2.0) * t) * 0.4) / 2.1
                mix += chord * attackRelease * 0.40
            }

            val limited = tanh(mix * 0.85)
            out[i] = (limited * 32760.0).toInt().coerceIn(-32768, 32767).toShort()
        }
    }

    fun exportWavFile(context: Context, bars: Int = 2): File {
        val samplesPerStep = (SAMPLE_RATE * 60.0 / bpm / 4.0).toInt()
        val totalSteps = NUM_STEPS * bars
        val totalSamples = samplesPerStep * totalSteps
        val pcmData = ShortArray(totalSamples)

        var offset = 0
        for (s in 0 until totalSteps) {
            val stepSamples = renderStepSamples(s % NUM_STEPS, samplesPerStep)
            System.arraycopy(stepSamples, 0, pcmData, offset, samplesPerStep)
            offset += samplesPerStep
        }

        val musicDir = context.getExternalFilesDir(Environment.DIRECTORY_MUSIC) ?: context.filesDir
        val outFile = File(musicDir, "AI_Studio_Track_${System.currentTimeMillis()}.wav")

        FileOutputStream(outFile).use { fos ->
            val byteDataSize = totalSamples * 2
            val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
            header.put("RIFF".toByteArray())
            header.putInt(36 + byteDataSize)
            header.put("WAVE".toByteArray())
            header.put("fmt ".toByteArray())
            header.putInt(16)
            header.putShort(1)
            header.putShort(1)
            header.putInt(SAMPLE_RATE)
            header.putInt(SAMPLE_RATE * 2)
            header.putShort(2)
            header.putShort(16)
            header.put("data".toByteArray())
            header.putInt(byteDataSize)
            fos.write(header.array())

            val pcmBuffer = ByteBuffer.allocate(byteDataSize).order(ByteOrder.LITTLE_ENDIAN)
            for (sample in pcmData) {
                pcmBuffer.putShort(sample)
            }
            fos.write(pcmBuffer.array())
        }
        return outFile
    }
}
